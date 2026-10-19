"""地基不变式：reduce 是 durable seq 的唯一分配者。

真问题（审计 track5-backbone BLK-1）：单事件拒绝分支产一条 durable ``warning`` 却
``return run`` 不推进 ``run.seq``，warning 落库占用了 ``run.seq+1``；下一条 durable 命令仍按
``run.seq+1`` 取号 → 撞 ``event_log UNIQUE(run_id, seq)`` → ``store.append`` 抛穿 ``bus.emit``
→ 崩循环。这里用真 store + 真总线证伪：任一"拒绝后再来 durable 命令"的序列都不得因取号相撞。
"""

from __future__ import annotations

import pytest

from questor.contracts.common import new_id
from questor.contracts.errors import ErrorKind
from questor.contracts.events import (
    AdvanceTurn,
    RecordToolResult,
    SetPermissionMode,
    SubmitMessage,
)
from questor.contracts.policy import PolicyIntent, PolicyPort, PolicyView
from questor.contracts.ports import StreamChunk
from questor.contracts.state_schema import Budget, ContentBlock, Message, Role, RunStatus
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.providers.fake import ScriptedProvider
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import Run
from questor.state.reduce import reduce


def _run(run_id: str) -> Run:
    return Run(run_id=run_id)


def _user(text: str) -> Message:
    return Message(id=new_id("msg"), role=Role.USER, content=(ContentBlock(type="text", text=text),), seq=0)


@pytest.fixture
async def bus_with_store():
    store = await SQLiteStore(":memory:").connect()
    bus = InProcessEventBus(store)
    yield bus, store
    await store.close()


async def _persist(bus: InProcessEventBus, events) -> None:
    for env in events:
        await bus.emit(env)


async def test_reject_then_next_durable_does_not_collide(bus_with_store) -> None:
    """被拒绝的 durable warning 与后续 durable 命令必须各占唯一 seq，落库不撞 UNIQUE。"""
    bus, store = bus_with_store
    run_id = new_id("run")

    run, evs = reduce(_run(run_id), SubmitMessage(run_id=run_id, content=_user("hi")))
    await _persist(bus, evs)
    run, evs = reduce(run, AdvanceTurn(run_id=run_id, turn=1))
    await _persist(bus, evs)

    # 未知 tool_call 的 result → reduce 拒绝并产一条 durable warning。
    run_after_reject, evs = reduce(run, RecordToolResult(run_id=run_id, tool_call_id="ghost", status="success", result="x"))
    assert [e.type for e in evs] == ["warning"], "该命令应被拒绝并只产 warning"
    await _persist(bus, evs)  # warning 落库

    # 下一条 durable 命令：修复前会复用 warning 占掉的 seq → bus.emit 抛 IntegrityError。
    run2, evs2 = reduce(run_after_reject, AdvanceTurn(run_id=run_id, turn=2))
    await _persist(bus, evs2)  # 若相撞，这里抛 sqlite3.IntegrityError

    seqs = [row["seq"] for row in await store.replay(run_id, after_seq=0)]
    assert seqs == sorted(seqs) and len(seqs) == len(set(seqs)), f"seq 出现重复/乱序：{seqs}"


async def test_repeated_rejections_take_distinct_seqs(bus_with_store) -> None:
    """连续多条被拒绝的命令，每条 warning 也要各占唯一 seq。"""
    bus, store = bus_with_store
    run_id = new_id("run")
    run, evs = reduce(_run(run_id), SubmitMessage(run_id=run_id, content=_user("hi")))
    await _persist(bus, evs)

    # 三次非法 permission mode（全部被拒绝产 warning）。
    for _ in range(3):
        run, evs = reduce(run, SetPermissionMode(run_id=run_id, mode="bogus", changed_by="test"))
        assert [e.type for e in evs] == ["warning"]
        await _persist(bus, evs)

    seqs = [row["seq"] for row in await store.replay(run_id, after_seq=0)]
    assert len(seqs) == len(set(seqs)), f"连续拒绝 warning 撞 seq：{seqs}"


class _PanickingPolicy(PolicyPort):
    id = "panic"
    fingerprint = "panic:1"

    def propose_action(self, view: PolicyView) -> PolicyIntent:
        raise RuntimeError("boom")


_ANSWER = [
    StreamChunk(kind="text", text="done"),
    StreamChunk(kind="finish", finish_reason="stop"),
]


async def test_policy_fault_with_store_does_not_crash_loop(tmp_path) -> None:
    """track5-backbone BLK-1 path A：策略故障的 durable warning 经 ``_live`` 发时会复用已占 seq，
    且 ``run = turn_start`` 回滚把 seq 游标倒退 → 落库撞 UNIQUE → 穿出 drive。真 store 下不得再发生。"""
    store = await SQLiteStore(str(tmp_path / "db.sqlite")).connect()
    try:
        loop = DefaultTurnLoop(
            provider=ScriptedProvider([_ANSWER] * 8),
            policy=_PanickingPolicy(),
            permission=DefaultPermissionEngine(),
            bus=InProcessEventBus(store),
            tool_for=lambda name: None,
            tools=(),
            store=store,
            workspace_root=tmp_path,
            model="m",
        )
        # 修复前：bus.emit(WARNING) 撞 UNIQUE 抛穿 → 这里 raise sqlite3.IntegrityError。
        final = await loop.drive(Run(run_id=new_id("run"), budget=Budget(max_turns=6)), "hi")
        assert final.status is RunStatus.FAILED
        assert final.error_stack[-1].kind is ErrorKind.POLICY_VIOLATION
        seqs = [row["seq"] for row in await store.replay(final.run_id, after_seq=0)]
        assert len(seqs) == len(set(seqs)), f"策略故障路径下 seq 相撞：{seqs}"
    finally:
        await store.close()
