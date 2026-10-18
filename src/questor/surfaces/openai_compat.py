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

from collections.abc import AsyncIterator
from typing import Any

from questor.contracts.events import Envelope, EventType
from questor.contracts.openai_wire import make_chunk

#: SSE 终结标记（design/02 §10：无原生续传，[DONE] 终结）。
DONE = "[DONE]"


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
