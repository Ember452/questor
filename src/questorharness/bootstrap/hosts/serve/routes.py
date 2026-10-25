"""框架无关的路由层：内存 transport 与回环 TCP 共用同一组 handler。

handler 只做四件事：解析请求、调用 authority / runtime、把结果编码成
Response。任何传输细节（cookie、端口、aiohttp）都不在这里。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from questorharness.bootstrap.hosts.serve import eventstream, refusals
from questorharness.bootstrap.hosts.serve.authority import Authority, TurnRecord
from questorharness.bootstrap.hosts.serve.broadcaster import Broadcaster
from questorharness.bootstrap.hosts.serve.transport import Request, Response
from questorharness.bootstrap.hosts.serve.wire import WireEncoder, stream_reset_frame
from questorharness.platform.session_storage import load_session_snapshot
from questorharness.profiles import ProfileError, load_profile

if TYPE_CHECKING:
    from questorharness.bootstrap.runtime import RuntimeBundle

PREFIX = "/rt/r1"
_HEARTBEAT_SECONDS = 15.0
_JSON_HEADERS = {"content-type": "application/json; charset=utf-8"}
_SSE_HEADERS = {"content-type": "text/event-stream; charset=utf-8", "cache-control": "no-cache"}


class HostLike(Protocol):
    """路由对宿主的依赖面（宿主实现它，路由不反向 import）。"""

    runtime: RuntimeBundle
    authority: Authority
    broadcaster: Broadcaster
    encoder: WireEncoder
    profile_root: Path
    profile_id: str

    def start_turn_task(self, record: TurnRecord) -> None: ...

    def cancel_turn(self, turn_id: str, client_id: str) -> bool: ...


def _ok(payload: dict[str, Any], *, status: int = 200) -> Response:
    """JSON 成功响应。"""
    return Response(
        status=status,
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=dict(_JSON_HEADERS),
    )


def _refusal(exc: refusals.Refusal) -> Response:
    """把拒绝码翻译成响应。"""
    return _ok({"code": exc.code, "message": exc.message}, status=exc.status)


def _error(status: int, code: str, message: str) -> Response:
    """非白名单错误码只用于协议层（如路由不存在）。"""
    return _ok({"code": code, "message": message}, status=status)


def _body_object(request: Request) -> dict[str, Any]:
    """解析 JSON 对象体；空体或非对象一律 400。"""
    if not request.body:
        raise refusals.Refusal(refusals.SUBMIT_INVALID, "missing body", status=400)
    try:
        parsed = json.loads(request.body)
    except json.JSONDecodeError as exc:
        raise refusals.Refusal(refusals.SUBMIT_INVALID, f"invalid json: {exc}", status=400) from exc
    if not isinstance(parsed, dict):
        raise refusals.Refusal(refusals.SUBMIT_INVALID, "body must be an object", status=400)
    return parsed


def _history_block(raw: Any) -> dict[str, Any]:
    """把快照里的内容块转成 wire 块；未知类型直接报错。"""
    if not isinstance(raw, dict):
        raise refusals.Refusal(
            refusals.SUBMIT_INVALID, "history block must be an object", status=500
        )
    kind = raw.get("type")
    if kind == "text":
        return {"type": "text", "text": str(raw.get("text", ""))}
    if kind == "image":
        return {"type": "image", "mediaType": str(raw.get("media_type", ""))}
    if kind == "tool_use":
        return {"type": "tool_use", "id": str(raw.get("id", "")), "name": str(raw.get("name", ""))}
    if kind == "tool_result":
        return {
            "type": "tool_result",
            "toolUseId": str(raw.get("tool_use_id", "")),
            "content": str(raw.get("content", "")),
            "isError": bool(raw.get("is_error", False)),
        }
    raise ValueError(f"unknown history block {kind!r}")


def _history_blocks(raw_blocks: Any) -> list[dict[str, Any]]:
    """历史回放对未知块降级为文本占位（不让整个端点 500）。"""
    blocks: list[dict[str, Any]] = []
    if not isinstance(raw_blocks, list):
        return blocks
    for block in raw_blocks:
        try:
            blocks.append(_history_block(block))
        except ValueError as exc:  # 未知块类型：可见降级，不静默
            blocks.append({"type": "text", "text": f"[unsupported block] {exc}"})
    return blocks


class Router:
    """把 HTTP 形状的请求映射到宿主能力。"""

    def __init__(self, host: HostLike) -> None:
        self._host = host

    async def __call__(self, request: Request) -> Response:
        """统一入口：路径分派 + 拒绝码收敛。"""
        path = request.path.split("?", 1)[0].rstrip("/")
        if path.startswith(PREFIX):
            path = path[len(PREFIX) :] or "/"
        try:
            if request.method == "POST" and path == "/submit":
                return self._submit(request)
            if request.method == "POST" and path == "/cancel":
                return self._cancel(request)
            if request.method == "POST" and path == "/approve":
                return self._approve(request)
            if request.method == "POST" and path == "/ask":
                return self._ask(request)
            if request.method == "GET" and path == "/events":
                return self._events(request)
            if request.method == "GET" and path == "/history":
                return self._history()
            if request.method == "GET" and path == "/profile":
                return self._profile(request)
            if request.method == "GET" and path == "/commands":
                return self._commands()
        except refusals.Refusal as exc:
            return _refusal(exc)
        return _error(404, refusals.NOT_FOUND, f"no route for {request.method} {path}")

    # ---- handlers -------------------------------------------------------
    def _submit(self, request: Request) -> Response:
        """提交一行；忙时入队（容量 1），幂等键重复则回同一回合。"""
        data = _body_object(request)
        line = data.get("line")
        request_id = data.get("clientRequestId")
        if not isinstance(line, str) or not line.strip():
            raise refusals.Refusal(refusals.SUBMIT_INVALID, "line is required", status=400)
        if not isinstance(request_id, str) or not request_id:
            raise refusals.Refusal(
                refusals.SUBMIT_INVALID, "clientRequestId is required", status=400
            )
        begin = self._host.authority.begin(
            request.client_id, request_id, line, via=request.via
        )
        if begin.kind == "replay":
            # 幂等重放必须回真实登记状态：排队中的请求不能谎报为 started。
            state = self._host.authority.state_of(request_id) or "running"
            return _ok({"turnId": begin.turn_id, "state": "started" if state == "running" else state})
        if begin.kind == "queued":
            return _ok(
                {"turnId": begin.turn_id, "state": "queued", "position": begin.position or 1},
                status=202,
            )
        record = self._host.authority.active_turn
        if record is None or record.turn_id != begin.turn_id:
            raise refusals.Refusal(refusals.TURN_BUSY, "lease lost before start")
        self._host.start_turn_task(record)
        return _ok({"turnId": begin.turn_id, "state": "started"}, status=202)

    def _cancel(self, request: Request) -> Response:
        """只有持有者可以取消。"""
        record = self._host.authority.active_turn
        if record is None:
            raise refusals.Refusal(refusals.TURN_NOT_OWNER, "no active turn")
        if not self._host.cancel_turn(record.turn_id, request.client_id):
            raise refusals.Refusal(refusals.TURN_NOT_OWNER, "not the turn owner")
        return _ok({"cancelled": True})

    def _approve(self, request: Request) -> Response:
        """结算权限审批。"""
        data = _body_object(request)
        prompt_id = data.get("id")
        decision = data.get("decision")
        if not isinstance(prompt_id, str) or decision not in ("approve", "deny"):
            raise refusals.Refusal(
                refusals.SUBMIT_INVALID, "id and decision are required", status=400
            )
        self._host.authority.settle(prompt_id, decision == "approve", request.client_id)
        return _ok({"ok": True})

    def _ask(self, request: Request) -> Response:
        """回答工具提问。"""
        data = _body_object(request)
        prompt_id = data.get("id")
        answer = data.get("answer")
        if not isinstance(prompt_id, str) or not isinstance(answer, str):
            raise refusals.Refusal(
                refusals.SUBMIT_INVALID, "id and answer are required", status=400
            )
        self._host.authority.settle(prompt_id, answer, request.client_id)
        return _ok({"ok": True})

    def _events(self, request: Request) -> Response:
        """SSE：生成器内先订阅再取重放快照（同一同步段，无 await），然后去重。"""
        last_id = eventstream.parse_last_event_id(request.last_event_id)
        relay = self._host.broadcaster

        async def stream() -> AsyncIterator[bytes]:
            subscriber = relay.subscribe()
            replay = relay.replay(last_id)
            replayed_to = replay.frames[-1][0] if replay.frames else 0
            try:
                if replay.gap:
                    watermark = relay.watermark
                    reset = stream_reset_frame(reason="replay_gap", watermark=watermark)
                    yield eventstream.format_sse(watermark, reset)
                for seq, frame in replay.frames:
                    yield eventstream.format_sse(seq, frame)
                while True:
                    try:
                        item = await asyncio.wait_for(subscriber.queue.get(), _HEARTBEAT_SECONDS)
                    except TimeoutError:
                        yield eventstream.heartbeat_bytes(relay.watermark)
                        continue
                    if item is None:
                        return
                    seq, frame = item
                    if seq <= replayed_to:
                        continue
                    if subscriber.overflowed:
                        # 事实帧挤掉过最旧帧：显式告诉客户端“丢过”，让它重取 /history。
                        subscriber.overflowed = False
                        watermark = relay.watermark
                        reset = stream_reset_frame(reason="replay_gap", watermark=watermark)
                        yield eventstream.format_sse(watermark, reset)
                    yield eventstream.format_sse(seq, frame)
            finally:
                relay.unsubscribe(subscriber)

        return Response(status=200, headers=dict(_SSE_HEADERS), stream=stream())

    def _history(self) -> Response:
        """会话快照直读，不新写存储。"""
        snapshot = load_session_snapshot(self._host.runtime.cwd)
        if snapshot is None:
            return _ok({"sessionId": self._host.runtime.session_id, "messages": []})
        raw_messages = snapshot.get("messages", [])
        messages = [
            {
                "role": str(message.get("role", "assistant")),
                "blocks": _history_blocks(message.get("content", [])),
            }
            for message in raw_messages
            if isinstance(message, dict)
        ]
        return _ok({"sessionId": str(snapshot.get("session_id", "")), "messages": messages})

    def _commands(self) -> Response:
        """指令目录（终端补全菜单与远端列表共用；顺序即 /help 顺序）。"""
        registry = self._host.runtime.commands
        return _ok(
            {
                "commands": [
                    {
                        "name": command.name,
                        "description": command.description,
                        "aliases": list(command.aliases),
                    }
                    for command in registry.list_commands()
                ]
            }
        )

    def _profile(self, request: Request) -> Response:
        """当前形态的能力位（页面 id → ready / declared / absent）。"""
        wanted = request.query.get("id") or self._host.profile_id
        try:
            profile = load_profile(self._host.profile_root, wanted)
        except ProfileError as exc:
            raise refusals.Refusal(refusals.PROFILE_UNKNOWN, str(exc), status=404) from exc
        return _ok(
            {
                "id": profile.name,
                "name": profile.name,
                "description": profile.description,
                "ui": {"capabilities": dict(profile.ui_capabilities)},
            }
        )
