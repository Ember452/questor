"""serve 宿主集成冒烟：提交 → 事件流 → 快照/历史。

引擎回合循环用注入的 ``handle_line`` 替身替代（它逐个产出真实 StreamEvent，
然后经 host 注入的 render_event 走完 wire → broadcaster → SSE 全链）；
其余环节（租约、编码、广播、SSE 字节、路由）都是真的。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from questorharness.bootstrap.hosts.serve import ServeHost
from questorharness.bootstrap.hosts.serve.authority import Authority
from questorharness.contracts.domain.events import (
    AssistantTextDelta,
    AssistantTurnComplete,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)
from questorharness.contracts.domain.message import ConversationMessage
from questorharness.contracts.usage import UsageSnapshot

PROFILE_YAML = """
name: coding
description: smoke
ui:
  capabilities:
    chat: ready
"""


async def _read_until(stream, needle: bytes, timeout: float = 5.0) -> bytes:  # type: ignore[no-untyped-def]
    """从 SSE 流读到指定帧出现为止。"""
    buffer = b""

    async def pump() -> None:
        nonlocal buffer
        async for chunk in stream:
            buffer += chunk
            if needle in buffer:
                return

    await asyncio.wait_for(pump(), timeout)
    return buffer


def test_full_turn_over_memory_transport(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """一个完整回合：turn_started → text → 工具 → message → turn_done。"""
    (tmp_path / "coding.yaml").write_text(PROFILE_YAML, encoding="utf-8")

    async def fake_handle_line(bundle, line, *, print_system, render_event, clear_output, user_message=None):  # type: ignore[no-untyped-def]
        assert line == "run it"
        await render_event(AssistantTextDelta(text="working"))
        await render_event(ToolExecutionStarted(tool_name="bash", tool_input={"cmd": "ls"}))
        await render_event(
            ToolExecutionCompleted(tool_name="bash", output="a.txt", is_error=False)
        )
        await render_event(
            AssistantTurnComplete(
                message=ConversationMessage.from_user_text("done"),
                usage=UsageSnapshot(input_tokens=5, output_tokens=6),
            )
        )
        return True

    from questorharness.bootstrap import runtime as runtime_module

    monkeypatch.setattr(runtime_module, "handle_line", fake_handle_line, raising=True)

    async def scenario() -> None:
        runtime = SimpleNamespace(cwd=str(tmp_path), session_id="sid")
        host = ServeHost(
            runtime,  # type: ignore[arg-type]
            authority=Authority(),
            profile_root=tmp_path,
        )
        response = await host.transport.request(
            "POST",
            "/rt/r1/submit",
            body=json.dumps({"line": "run it", "clientRequestId": "req-1"}).encode(),
        )
        assert response.status == 202
        turn_id = json.loads(response.body)["turnId"]
        await asyncio.gather(*host._tasks.values())  # noqa: SLF001 - 等待回合任务收尾
        stream = await host.transport.request("GET", "/rt/r1/events", last_event_id="0")
        assert stream.stream is not None
        payload = await _read_until(stream.stream, b'"turn_done"')
        for expected in (b"turn_started", b'"text"', b"tool_dispatch", b"tool_result", b'"message"'):
            assert expected in payload, expected
        assert turn_id.encode() in payload
        assert host.authority.active_turn is None
        history = await host.transport.request("GET", "/rt/r1/history")
        assert history.status == 200

    asyncio.run(scenario())


def test_cancel_marks_turn_done_cancelled(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """取消后 turn_done.cancelled = true，租约被释放。"""
    (tmp_path / "coding.yaml").write_text(PROFILE_YAML, encoding="utf-8")

    async def hanging_handle_line(bundle, line, *, print_system, render_event, clear_output, user_message=None):  # type: ignore[no-untyped-def]
        await asyncio.sleep(30)
        return True

    from questorharness.bootstrap import runtime as runtime_module

    monkeypatch.setattr(runtime_module, "handle_line", hanging_handle_line, raising=True)

    async def scenario() -> None:
        runtime = SimpleNamespace(cwd=str(tmp_path), session_id="sid")
        host = ServeHost(
            runtime,  # type: ignore[arg-type]
            authority=Authority(),
            profile_root=tmp_path,
        )
        submit = await host.transport.request(
            "POST",
            "/rt/r1/submit",
            body=json.dumps({"line": "slow", "clientRequestId": "c1"}).encode(),
            client_id="owner",
        )
        assert submit.status == 202
        await asyncio.sleep(0.05)
        cancel = await host.transport.request("POST", "/rt/r1/cancel", client_id="owner")
        assert cancel.status == 200
        await asyncio.gather(*host._tasks.values(), return_exceptions=True)
        replay = host.broadcaster.replay(0)
        kinds = [frame["kind"] for _, frame in replay.frames]
        assert "turn_done" in kinds
        done = next(frame for _, frame in replay.frames if frame["kind"] == "turn_done")
        assert done["cancelled"] is True
        assert host.authority.active_turn is None

    asyncio.run(scenario())
