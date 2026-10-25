"""回到底线：回合没结束，用户也能继续输入；第二句排上队并可见。"""

from __future__ import annotations

import asyncio
import io
import time
from types import SimpleNamespace

from rich.console import Console

from questorharness.bootstrap.hosts import terminal_client
from questorharness.bootstrap.hosts.serve.authority import Authority
from questorharness.bootstrap.hosts.serve.broadcaster import Broadcaster
from questorharness.bootstrap.hosts.serve.routes import Router
from questorharness.bootstrap.hosts.serve.transport import MemoryTransport
from questorharness.bootstrap.hosts.serve.wire import WireEncoder
from questorharness.bootstrap.hosts.terminal import strings

PROFILE_YAML = "name: coding\nui:\n  capabilities:\n    chat: ready\n"


class _HoldingHost:
    """回合开始时**不**结束：只有测试显式调用 `finish_next()` 才收尾。

    这正是真实宿主的行为（引擎跑多久由引擎决定），也是"回合中可输入"
    这条需求唯一能判红的姿态。
    """

    def __init__(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        (tmp_path / "coding.yaml").write_text(PROFILE_YAML, encoding="utf-8")
        self.runtime = SimpleNamespace(cwd=str(tmp_path), session_id="sid")
        self.authority = Authority()
        self.broadcaster = Broadcaster()
        self.encoder = WireEncoder()
        self.profile_root = tmp_path
        self.profile_id = "coding"
        self.transport = MemoryTransport(Router(self))
        self.running: list[object] = []

    def start_turn_task(self, record) -> None:  # type: ignore[no-untyped-def]
        self.running.append(record)

    def cancel_turn(self, turn_id: str, client_id: str) -> bool:
        return True

    def finish_next(self) -> None:
        """收尾一个回合，并按真实宿主的语义推进排队槽。"""

        record = self.running.pop(0)
        self.authority.finish(record.turn_id)  # type: ignore[attr-defined]
        queued = self.authority.pop_queued()
        if queued is not None:
            self.start_turn_task(queued)
        asyncio.get_running_loop().create_task(
            self.broadcaster.publish({"kind": "turn_done", "outcome": "completed", "durationMs": 1})
        )


def test_second_line_is_queued_while_the_first_turn_runs(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    host = _HoldingHost(tmp_path)
    step = {"n": 0}

    def fake_input(_prompt: str = "") -> str:
        step["n"] += 1
        if step["n"] == 1:
            return "one"
        if step["n"] == 2:
            time.sleep(0.03)
            return "two"
        time.sleep(0.3)  # 留出窗口让驱动任务把两个回合成完
        raise EOFError

    monkeypatch.setattr("builtins.input", fake_input)
    output = Console(file=io.StringIO(), force_terminal=False)

    async def driver() -> None:
        while len(host.running) == 0:
            await asyncio.sleep(0.005)
        await asyncio.sleep(0.05)
        host.finish_next()
        await asyncio.sleep(0.05)
        host.finish_next()

    async def scenario() -> int:
        asyncio.get_running_loop().create_task(driver())
        return await asyncio.wait_for(
            terminal_client.run_terminal_client(host, console=output), timeout=5.0
        )

    assert asyncio.run(scenario()) == 0
    text = output.file.getvalue()  # type: ignore[union-attr]
    assert strings.QUEUED in text, text
    assert text.count("completed") == 2, text


def test_queue_receipt_shows_the_depth_in_the_status_bar(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """排队回执要跟着状态栏显示队列深度，否则用户不知道排上了。"""

    host = _HoldingHost(tmp_path)
    renderer = terminal_client.TerminalRenderer(host, Console(file=io.StringIO(), force_terminal=False))
    renderer.note_queued()
    text = renderer._console.file.getvalue()  # type: ignore[union-attr]
    assert "队列 1" in text
