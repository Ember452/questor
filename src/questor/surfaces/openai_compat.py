"""L6 OpenAI 兼容投影适配器（ADR-0043/0044；design/02 §9 X5/§10）。

**投影适配器，不是第二写者/第二真相**：入站 ``/v1/chat/completions`` 经 **Command Inbox** 提交
``SubmitMessage``（C16，禁直接 reduce）；出站**只读**订阅该 run 的事件总线、投影成 OpenAI SSE。
带外投影复用 ``EventServer`` 已挂的唯一 bus 级 observer——本面**绝不**再调 ``log_envelope``
（ADR-0033 / pitfalls #5，防多 surface 双投）。

**无原生续传**：外部客户端断连即经 inbox 提 ``Cancel``，不提供 ``after_seq`` 重放（桌面 ``/events``
才有续传）；内核三终态（completed/cancelled/failed）不因兼容面合并或简化。非文本/语音 part 归一拒绝
（ADR-0044，见 :func:`questor.contracts.openai_wire.extract_last_user_text`）。
"""

from __future__ import annotations

import contextlib
import json
import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from questor.contracts.common import new_id
from questor.contracts.events import Envelope, EventType
from questor.contracts.openai_wire import OpenAIRequestError, error_object, extract_last_user_text, make_chunk
from questor.kernel.seed import SeedRejected

if TYPE_CHECKING:  # 仅类型：避免与 http_sse 的模块期循环 import（create_app 内延迟调 mount）。
    from questor.surfaces.http_sse import EventServer

#: SSE 终结标记（design/02 §10：无原生续传，[DONE] 终结）。
DONE = "[DONE]"

#: 本适配器消费的 questor 事件类型（design/02 §10 映射表的定义域）。漂移门
#: ``scripts/check_openai_compat_schema.py`` 断言本集 ⊆ ``contracts`` EventType（映射引用未知事件即判红）。
PROJECTED_EVENT_TYPES: frozenset[str] = frozenset(
    {
        EventType.RUN_STARTED,
        EventType.TEXT_DELTA,
        EventType.REASONING_DELTA,
        EventType.TOOL_STARTED,
        EventType.TOOL_COMPLETED,
        EventType.RUN_COMPLETED,
        EventType.RUN_CANCELLED,
        EventType.RUN_FAILED,
    }
)


async def project_openai_stream(
    envelopes: AsyncIterator[Envelope],
    *,
    completion_id: str,
    model: str,
    created: int,
) -> AsyncIterator[Any]:
    """把一条 run 的事件流投影成 OpenAI ``chat.completion.chunk`` 帧序列（映射表见 ADR-0043）。

    产出物既可是 chunk dict，也可是终结哨兵 :data:`DONE`。首帧发 role delta；``text_delta``→content、
    ``tool_started``→tool_calls、``run_failed``→末帧携 error（编进 finish_reason）、
    ``run_completed``/``run_cancelled``→``finish_reason:"stop"`` + ``[DONE]``。见终态即停。
    """
    started = False
    async for env in envelopes:
        if not started:
            started = True
            # 首帧：role delta（content 空）+ 专有 run 关联进 x_questor（不污染标准字段）。
            yield make_chunk(completion_id, created, model, {"role": "assistant", "content": ""}, x_questor={"run_id": env.run_id})
        etype = env.type
        if etype == EventType.TEXT_DELTA:
            yield make_chunk(completion_id, created, model, {"content": env.data.get("delta", "")})
        elif etype == EventType.REASONING_DELTA:
            # 推理流：OpenAI 无标准位，走扩展位 x_questor + 常见 reasoning_content 别名。
            yield make_chunk(completion_id, created, model, {"reasoning_content": env.data.get("delta", "")})
        elif etype == EventType.TOOL_STARTED:
            yield make_chunk(
                completion_id,
                created,
                model,
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": env.data.get("tool_call_id"),
                            "type": "function",
                            "function": {"name": env.data.get("name", ""), "arguments": ""},
                        }
                    ]
                },
            )
        elif etype == EventType.TOOL_COMPLETED:
            # 工具结果不进标准 assistant 流（OpenAI 由客户端回 tool 消息）；仅 x_questor 有界状态。
            yield make_chunk(completion_id, created, model, {}, x_questor={"tool_status": env.data.get("status")})
        elif etype == EventType.RUN_FAILED:
            # 错误编进末帧 finish_reason + x_questor.error（design/02 §10），再 [DONE]。
            yield make_chunk(completion_id, created, model, {}, finish_reason="stop", x_questor={"error": env.data.get("error")})
            yield DONE
            return
        elif etype in (EventType.RUN_COMPLETED, EventType.RUN_CANCELLED):
            xq = {"cancelled": True} if etype == EventType.RUN_CANCELLED else None
            yield make_chunk(completion_id, created, model, {}, finish_reason="stop", x_questor=xq)
            yield DONE
            return


async def _stream_with_cancel(server: EventServer, run_id: str, completion_id: str, model: str, created: int) -> AsyncIterator[dict[str, str]]:
    """投影事件流为 OpenAI SSE 帧；未达终态即关流（客户端断连）→ 经 inbox 提 ``Cancel``（不假装 resume）。

    断连取消走 Command Inbox（C16），非 out-of-band 硬杀；已达终态则不取消（cancel 对终态为 no-op）。"""
    completed = False
    try:
        async for frame in project_openai_stream(server.bus.subscribe(run_id, 0), completion_id=completion_id, model=model, created=created):
            if frame == DONE:
                completed = True
                yield {"data": "[DONE]"}
            else:
                yield {"data": json.dumps(frame, ensure_ascii=False)}
    finally:
        if not completed:  # 无原生续传：客户端断连即取消该 run；终态/未知 run 的 cancel 会抛 409 → 清理路径吞掉（#175）。
            with contextlib.suppress(HTTPException):
                await server.cancel(run_id)


async def _collect_final_text(server: EventServer, run_id: str) -> str:
    """非流式：读到终态，聚合可见文本（一次性收全，无游标续传）。

    客户端在聚合途中断连 → 本协程被取消，finally 经 inbox 提 ``Cancel`` 收敛该 run，
    不再让它在后台继续烧 provider 费用（#175）。"""
    buf: list[str] = []
    reached_terminal = False
    try:
        async for env in server.bus.subscribe(run_id, 0):
            if env.type == EventType.TEXT_DELTA:
                buf.append(env.data.get("delta", ""))
            elif env.type in (EventType.RUN_COMPLETED, EventType.RUN_CANCELLED, EventType.RUN_FAILED):
                reached_terminal = True
                break
    finally:
        if not reached_terminal:  # 断连/取消：best-effort 收敛 run；终态竞态的 409 吞掉
            with contextlib.suppress(HTTPException):
                await server.cancel(run_id)
    return "".join(buf)


def _completion_object(completion_id: str, created: int, model: str, content: str, run_id: str) -> dict[str, Any]:
    """非流式聚合体：标准 ``chat.completion`` 形状 + ``x_questor.run_id``。"""
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "x_questor": {"run_id": run_id},
    }


def mount_openai_routes(app: FastAPI, server: EventServer, *, api_keys: list[str], default_model: str = "questor") -> None:
    """把 OpenAI 兼容端点挂到 ``app``：**强制 API-key/bearer fail-closed**（无/错 key→401）。

    密钥比对不存不日（C20）；非文本/语音入站经 :func:`extract_last_user_text` 归一拒绝（400、不起 run）。
    本函数仅在配置了 ``api_keys`` 时挂载（鉴权外部 lane）；桌面 sidecar loopback 面不走此路。"""
    keyset = frozenset(api_keys)
    # W6-010：会话归属登记——session_id 首次由哪个 API key 创建就绑定该 key；其他 key 拿同一
    # session_id 作 seed 会读到他人最近 transcript（跨 key 信息泄露），一律 403 拒。
    session_owner: dict[str, str] = {}

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Any:
        auth = request.headers.get("authorization", "")
        token = auth[len("Bearer "):].strip() if auth.startswith("Bearer ") else None
        if not keyset or token is None or token not in keyset:
            return JSONResponse(status_code=401, content=error_object("invalid_api_key", "missing or invalid API key", error_type="authentication_error"))
        body = await request.json()
        try:
            text = extract_last_user_text(body.get("messages"))
        except OpenAIRequestError as exc:
            # 归一拒绝：不起 run、不建 Command、不崩、不静默降级（ADR-0044）。
            return JSONResponse(status_code=exc.http_status, content=error_object(exc.code, exc.message, param=exc.param))
        model = body.get("model", default_model)
        completion_id = new_id("chatcmpl")
        created = int(time.time())
        session_id = body.get("session_id")
        if session_id is not None:
            owner = session_owner.get(session_id)
            if owner is not None and owner != token:
                return JSONResponse(status_code=403, content=error_object("forbidden", "session_id belongs to a different API key", param="session_id"))
            session_owner.setdefault(session_id, token)
        try:
            run_id = await server.start_run(
                text, session_id=session_id, seed_refs=body.get("seed_refs")
            )  # SubmitMessage 经 inbox（C16）；起一个独立 run。
        except SeedRejected as exc:
            return JSONResponse(status_code=400, content=error_object("seed_rejected", str(exc), param="seed_refs"))
        if body.get("stream"):
            return EventSourceResponse(_stream_with_cancel(server, run_id, completion_id, model, created))
        content = await _collect_final_text(server, run_id)
        return JSONResponse(_completion_object(completion_id, created, model, content, run_id))


__all__ = ["DONE", "PROJECTED_EVENT_TYPES", "mount_openai_routes", "project_openai_stream"]
