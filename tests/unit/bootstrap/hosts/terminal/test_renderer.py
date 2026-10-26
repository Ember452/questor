"""`renderer.py`：SSE 解析、帧渲染、队列回执。"""

from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace

from rich.console import Console

from questorharness.bootstrap.hosts.serve.authority import Authority
from questorharness.bootstrap.hosts.serve.wire import WireEncoder
from questorharness.bootstrap.hosts.terminal import renderer as renderer_module


def _renderer() -> tuple[renderer_module.TerminalRenderer, io.StringIO]:
    buffer = io.StringIO()
    host = SimpleNamespace(
        transport=SimpleNamespace(request=None),
        authority=Authority(),
        broadcaster=SimpleNamespace(),
        encoder=WireEncoder(),
        runtime=SimpleNamespace(cwd=".", session_id="sid"),
    )
    instance = renderer_module.TerminalRenderer(
        host, Console(file=buffer, force_terminal=False), profile_name="coding"
    )
    return instance, buffer


def test_frame_from_sse_reads_the_data_line() -> None:
    assert renderer_module.frame_from_sse(b'id: 1\nevent: frame\ndata: {"kind":"text"}\n') == {
        "kind": "text"
    }


def test_frame_from_sse_tolerates_heartbeats_and_bad_json() -> None:
    assert renderer_module.frame_from_sse(b"id: 1\nevent: ping\n") is None
    assert renderer_module.frame_from_sse(b"id: 1\ndata: not-json\n") is None


def test_todos_frame_renders_a_checklist_card() -> None:
    instance, buffer = _renderer()

    async def scenario() -> None:
        await instance._render(
            {
                "kind": "todos",
                "path": "TODO.md",
                "items": [{"text": "写文档", "checked": True}],
            }
        )

    asyncio.run(scenario())
    text = buffer.getvalue()
    assert "TODO.md" in text and "写文档" in text


def test_queued_receipt_updates_footer_depth() -> None:
    instance, buffer = _renderer()
    instance.note_queued()
    assert "队列 1" in buffer.getvalue()


def test_pending_turns_are_counted_and_cleared_on_turn_done() -> None:
    instance, _ = _renderer()
    instance.expect_turn()

    async def scenario() -> None:
        await instance._render(
            {
                "kind": "turn_done",
                "turnId": "t",
                "cancelled": False,
                "outcome": "completed",
                "durationMs": 1,
                "checkpointTurn": False,
            }
        )

    asyncio.run(scenario())
    assert instance.pending_turns == 0
    assert instance.done.is_set()


def _capture_post(instance: renderer_module.TerminalRenderer) -> list[tuple[str, str, bytes]]:  # type: ignore[no-untyped-def]
    """替换宿主 transport：记录每次 POST，供结算断言。"""
    posted: list[tuple[str, str, bytes]] = []

    async def _request(method: str, path: str, body: bytes = b"", **_kw: object) -> SimpleNamespace:
        posted.append((method, path, body))
        return SimpleNamespace(status=200, body=b"{}", headers={}, stream=None)

    instance._host.transport.request = _request  # type: ignore[attr-defined]
    return posted


def test_approval_interrupt_settles_deny_and_does_not_kill_the_repl(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """波 B Ctrl-C 四语义表：审批中 Ctrl-C = deny，异常不得击穿 REPL 退出。"""
    import json

    from questorharness.bootstrap.hosts.terminal import wire_view as view

    instance, buffer = _renderer()
    posted = _capture_post(instance)

    async def _interrupt(_prompt: str, **_kw: object) -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr(instance, "_read_answer", _interrupt)

    asyncio.run(instance._ask_approval(view.ApprovalItem("p1", "edit", "a.py", "")))
    assert posted and posted[0][:2] == ("POST", "/rt/r1/approve")
    assert json.loads(posted[0][2])["decision"] == "deny"
    assert "已中断" in buffer.getvalue()


def test_ask_interrupt_settles_unanswered(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """提问中 Ctrl-C = 未回答（空答案结算），不得击穿 REPL 退出。"""
    import json

    from questorharness.bootstrap.hosts.terminal import wire_view as view

    instance, buffer = _renderer()
    posted = _capture_post(instance)

    async def _interrupt(_prompt: str, **_kw: object) -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr(instance, "_read_answer", _interrupt)

    asyncio.run(instance._answer_question(view.AskItem("q1", "选哪个？")))
    assert posted and posted[0][:2] == ("POST", "/rt/r1/ask")
    assert json.loads(posted[0][2]) == {"id": "q1", "answer": ""}
    assert "已中断" in buffer.getvalue()
