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
