"""reduce 的 WriteMemory 分支（T11；DoD③/⑤）。钉死：占一个 durable seq + 发 memory_written
有界回执（**无原文**），记忆正文绝不进 Domain_State；超限 fail-closed 拒。落库副作用属 kernel，不在 reduce。"""

from __future__ import annotations

from questor.contracts.events import EventType, WriteMemory
from questor.contracts.memory import MemoryScope, MemoryWrite, MemoryWriteKind
from questor.state.domain_state import Run
from questor.state.reduce import reduce


def test_write_memory_emits_bounded_ack_without_text() -> None:
    run = Run(run_id="r1", seq=3, turn=1)
    cmd = WriteMemory(
        run_id="r1",
        payload=MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.USER, text="SECRET-TEXT-MUST-NOT-LEAK"),
    )
    new, events = reduce(run, cmd)
    assert new.seq == 4  # 受理时占一个 durable seq（design/02 §10）
    assert len(events) == 1
    ev = events[0]
    assert ev.type == EventType.MEMORY_WRITTEN
    assert ev.data["kind"] == "daily"
    assert ev.data["source"] == "daily"  # §6-6：source 是真实 MemorySource（非 kind.value）
    assert "SECRET-TEXT-MUST-NOT-LEAK" not in str(ev.data)  # DoD⑤：事件不含原文
    assert new.context.items == run.context.items  # 记忆正文不进 Domain_State
    assert new.context.recovery_pointers == run.context.recovery_pointers


def test_write_memory_oversize_fail_closed() -> None:
    run = Run(run_id="r1", seq=0, turn=0)
    cmd = WriteMemory(
        run_id="r1",
        payload=MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.USER, text="x" * (16 * 1024 + 1)),
    )
    new, events = reduce(run, cmd)
    assert new.seq == 0  # 拒绝：不占 seq、状态不变
    assert events[0].type == EventType.WARNING
