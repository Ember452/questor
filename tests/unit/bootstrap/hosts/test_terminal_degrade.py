"""渲染降级：单帧异常必须可见、且不杀死事件消费循环。"""

from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace

from rich.console import Console

from questorharness.bootstrap.hosts import terminal_client
from questorharness.bootstrap.hosts.serve.authority import Authority
from questorharness.bootstrap.hosts.serve.broadcaster import Broadcaster
from questorharness.bootstrap.hosts.serve.transport import MemoryTransport
from questorharness.bootstrap.hosts.serve.wire import WireEncoder
from questorharness.bootstrap.hosts.terminal import cards, strings


class _Host:
    def __init__(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        self.runtime = SimpleNamespace(cwd=str(tmp_path), session_id="sid")
        self.authority = Authority()
        self.broadcaster = Broadcaster()
        self.encoder = WireEncoder()
        self.profile_root = tmp_path
        self.profile_id = "coding"
        self.transport = MemoryTransport(lambda request: None)  # type: ignore[arg-type]

    def start_turn_task(self, record) -> None:  # type: ignore[no-untyped-def]
        raise AssertionError("not used")

    def cancel_turn(self, turn_id: str, client_id: str) -> bool:
        return True


def test_render_exception_degrades_and_the_frame_after_it_still_renders(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    host = _Host(tmp_path)
    buffer = io.StringIO()
    renderer = terminal_client.TerminalRenderer(host, Console(file=buffer, force_terminal=False))

    original = cards.render_item
    state = {"boom": True}

    def flaky(item):  # type: ignore[no-untyped-def]
        if state["boom"]:
            state["boom"] = False
            raise RuntimeError("坏图元")
        return original(item)

    monkeypatch.setattr(cards, "render_item", flaky)

    async def scenario() -> None:
        await renderer._render({"kind": "tool_dispatch", "tool": "bash"})
        await renderer._render({"kind": "notice", "level": "info", "text": "后续帧照常"})

    asyncio.run(scenario())
    text = buffer.getvalue()
    assert "渲染失败" in text
    assert "坏图元" in text
    assert "后续帧照常" in text


def test_unknown_kind_is_rendered_not_swallowed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    host = _Host(tmp_path)
    buffer = io.StringIO()
    renderer = terminal_client.TerminalRenderer(host, Console(file=buffer, force_terminal=False))
    asyncio.run(renderer._render({"kind": "future_kind", "anything": 1}))
    text = buffer.getvalue()
    assert "future_kind" in text
    assert "未登记" in text


def test_timeout_answer_is_treated_as_deny(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """超时不能永远挂着：按 deny 结算，并显式告知用户。"""

    host = _Host(tmp_path)
    buffer = io.StringIO()
    renderer = terminal_client.TerminalRenderer(host, Console(file=buffer, force_terminal=False))
    recorded: list[dict[str, object]] = []

    async def fake_request(method, path, **kwargs):  # type: ignore[no-untyped-def]
        import json

        recorded.append({"path": path, **json.loads(kwargs["body"])})
        return SimpleNamespace(status=200, body=b"{}")

    host.transport.request = fake_request  # type: ignore[attr-defined]
    monkeypatch.setattr(renderer, "_prompt_timeout", lambda: 0.01)

    def slow_input(_prompt: str = "") -> str:
        import time

        time.sleep(0.2)
        return "y"

    monkeypatch.setattr("builtins.input", slow_input)

    from questorharness.bootstrap.hosts.terminal import wire_view as view

    asyncio.run(renderer._ask_approval(view.ApprovalItem("p1", "bash", "rm", "")))
    assert recorded == [{"path": "/rt/r1/approve", "id": "p1", "decision": "deny"}]
    assert strings.APPROVAL_TIMEOUT.strip() in buffer.getvalue()
