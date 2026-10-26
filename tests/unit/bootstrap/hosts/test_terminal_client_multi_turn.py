"""REPL 必须能连续跑多个回合（消费循环不得在 turn_done 后自尽）。"""

from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace

from rich.console import Console

from questorharness.bootstrap.hosts import terminal_client
from questorharness.bootstrap.hosts.serve.authority import Authority
from questorharness.bootstrap.hosts.serve.broadcaster import Broadcaster
from questorharness.bootstrap.hosts.serve.routes import Router
from questorharness.bootstrap.hosts.serve.transport import MemoryTransport
from questorharness.bootstrap.hosts.serve.wire import WireEncoder

PROFILE_YAML = "name: coding\nui:\n  capabilities:\n    chat: ready\n"


class _FakeHost:
    """只实现 REPL 需要的宿主面：提交即产生一个立刻完成的回合。"""

    def __init__(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        (tmp_path / "coding.yaml").write_text(PROFILE_YAML, encoding="utf-8")
        self.runtime = SimpleNamespace(cwd=str(tmp_path), session_id="sid")
        self.authority = Authority()
        self.broadcaster = Broadcaster()
        self.encoder = WireEncoder()
        self.profile_root = tmp_path
        self.profile_id = "coding"
        self.transport = MemoryTransport(Router(self))

    def start_turn_task(self, record) -> None:  # type: ignore[no-untyped-def]
        """异步发布 turn_done，并立即释放租约（模拟回合结束）。"""
        self.authority.finish(record.turn_id)

        async def _finish() -> None:
            await asyncio.sleep(0)
            await self.broadcaster.publish(
                {"kind": "turn_done", "outcome": "completed", "durationMs": 1}
            )

        asyncio.get_running_loop().create_task(_finish())

    def cancel_turn(self, turn_id: str, client_id: str) -> bool:
        return True


def test_two_turns_both_complete(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """连输两句 → 两句都必须收到 turn_done（回归：第一轮后订阅被 return 掉）。"""
    host = _FakeHost(tmp_path)
    lines = iter(["one", "two"])

    def fake_input(_prompt: str = "") -> str:
        try:
            return next(lines)
        except StopIteration as exc:
            raise EOFError from exc

    monkeypatch.setattr("builtins.input", fake_input)
    output = Console(file=io.StringIO(), force_terminal=False)

    async def scenario() -> int:
        return await asyncio.wait_for(
            terminal_client.run_terminal_client(host, console=output), timeout=3.0
        )

    assert asyncio.run(scenario()) == 0
    text = output.file.getvalue()  # type: ignore[union-attr]
    assert text.count("完成") == 2, text
