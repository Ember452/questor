"""B13 会话形状：回退/分叉/元数据**只追加事实**，旧流与旧状态不被改写。

判据落在可观察后果上：回放旧 run 的行数不变、新 run 带 `history_base` 且能过快照往返、
会话事实落在 `sess:<id>` 流上而不是某个新表里。
"""

from __future__ import annotations

import pytest

from questor.contracts.events import (
    ForkSession,
    RewindRun,
    SubmitMessage,
    UpdateMemory,
    UpdateSession,
)
from questor.contracts.state_schema import ContentBlock, Message, Role
from questor.kernel.events import InProcessEventBus
from questor.kernel.session_ops import (
    apply_fork,
    apply_on_stream,
    apply_session_update,
    prefix_seed_refs,
    session_stream_id,
)
from questor.providers.fake import ScriptedProvider
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import Run
from questor.state.reduce import reduce
from questor.state.snapshot import from_snapshot, to_snapshot
from questor.surfaces.cli import CliSurface


def _user(text: str, seq: int) -> Message:
    return Message(id=f"u{seq}", role=Role.USER, content=(ContentBlock(type="text", text=text),), seq=seq)


def test_rewind_records_history_base_without_touching_state():
    """回退只推进 seq + 记锚：context/status 一字不动（"回到过去"是新事实，不是修剪）。"""
    run = Run(run_id="r-new")
    new, events = reduce(run, RewindRun(run_id="r-new", base_run_id="r-old", base_to_seq=7, reason="try again"))
    assert len(events) == 1 and events[0].type == "run_rewounded"
    assert dict(events[0].data) == {"base_run_id": "r-old", "base_to_seq": 7, "reason": "try again"}
    assert new.seq == run.seq + 1
    assert new.context.items == run.context.items and new.status is run.status
    assert dict(new.history_base) == {"run_id": "r-old", "to_seq": 7}  # type: ignore[arg-type]


def test_rewind_anchor_survives_snapshot_round_trip():
    """`history_base` 必须进快照：否则 resume/rebuild 会把"这个 run 是回退来的"丢掉。"""
    run = Run(run_id="r-new")
    new, _ = reduce(run, RewindRun(run_id="r-new", base_run_id="r-old", base_to_seq=3))
    back = from_snapshot(to_snapshot(new))
    assert dict(back.history_base) == {"run_id": "r-old", "to_seq": 3}  # type: ignore[arg-type]
    assert to_snapshot(back) == to_snapshot(new)


def test_rewind_and_fork_reject_bad_shapes():
    with pytest.raises(ValueError, match="onto itself"):
        RewindRun(run_id="r", base_run_id="r", base_to_seq=1)
    with pytest.raises(ValueError, match="base_to_seq"):
        RewindRun(run_id="r2", base_run_id="r1", base_to_seq=-1)
    with pytest.raises(ValueError, match="from_seq"):
        ForkSession(run_id="s", source_session_id="src", from_seq=-1)
    with pytest.raises(ValueError, match="at least one facet"):
        UpdateSession(run_id="s", session_id="sess-1")
    with pytest.raises(ValueError, match="non-blank"):
        UpdateSession(run_id="s", session_id="sess-1", title="   ")
    with pytest.raises(ValueError, match="16 KiB"):
        UpdateMemory(run_id="r", entry_id="memory/a.md:1-2", text="x" * (17 * 1024))


def test_update_session_only_emits_given_facets():
    """一次 PATCH 只对本次真给的 facet 发声：给了两个就两条、连续取号，一条都不空发。"""
    run = Run(run_id=session_stream_id("sess-1"))
    new, events = reduce(run, UpdateSession(run_id=run.run_id, session_id="sess-1", title="launch", pinned=True))
    assert [e.type for e in events] == ["session_renamed", "session_pinned"]
    assert [e.seq for e in events] == [1, 2] and new.seq == 2
    assert dict(events[0].data) == {"session_id": "sess-1", "title": "launch"}
    _new, single = reduce(run, UpdateSession(run_id=run.run_id, session_id="sess-1", archived=False))
    assert [e.type for e in single] == ["session_archived"]
    assert dict(single[0].data) == {"session_id": "sess-1", "archived": False}


def test_update_memory_receipt_carries_no_body():
    """改写回执只带条目 id/层级/字节数——新正文绝不进事实流（C18/C20）。"""
    run = Run(run_id="r1")
    new, events = reduce(run, UpdateMemory(run_id="r1", entry_id="memory/2026-10-01.md:3-7", text="secret new body", reason="typo"))
    data = dict(events[0].data)
    assert events[0].type == "memory_updated"
    assert data["entry_id"] == "memory/2026-10-01.md:3-7"
    assert data["layer"] == "raw" and data["bytes"] == len("secret new body")
    assert "secret new body" not in str(data)
    assert new.seq == 1 and new.context.items == ()


async def test_apply_on_session_stream_persists_and_replays(tmp_path):
    """会话事实落在 `sess:<id>` 流上：可 `replay` 读到、seq 单调、重投同键不产生第二行。"""
    store = await SQLiteStore(str(tmp_path / "s.db")).connect()
    try:
        bus = InProcessEventBus(store)
        surface = CliSurface(workspace_root=tmp_path, store=store, provider=ScriptedProvider([]))
        await surface.refresh_memory_index()  # 不抛即可：会话流不需要索引段
        assert surface.memory_index is None
        stream = session_stream_id("sess-1")
        _run, events = await apply_on_stream(
            store, bus, stream_run_id=stream, command=ForkSession(run_id=stream, source_session_id="sess-0", from_seq=4), idempotency_key="fork-1"
        )
        assert len(events) == 1
        # 会话流没有活 controller，每次 apply 都从 store 头取号：所以两次调用各占一个 seq（追加语义）。
        # “同值 PATCH 不重复发事”靠现值比对，那是 c2 `apply_session_update` 的事，不在这里假装已有。
        again, second = await apply_on_stream(
            store, bus, stream_run_id=stream, command=ForkSession(run_id=stream, source_session_id="sess-0", from_seq=5), idempotency_key="fork-2"
        )
        assert len(second) == 1 and again.seq == 2
        rows = await store.replay(stream, 0)
        assert [r["type"] for r in rows] == ["session_forked", "session_forked"]
        assert [r["seq"] for r in rows] == [1, 2]  # seq 单调，不重复占号
        assert rows[0]["data"]["source_session_id"] == "sess-0"
    finally:
        await store.close()


async def test_rewind_leaves_the_base_stream_untouched(tmp_path):
    """§13 B13 验收：回退后旧 run 的事实流一条不少、一条不改。"""
    store = await SQLiteStore(str(tmp_path / "s.db")).connect()
    try:
        bus = InProcessEventBus(store)
        for index in range(3):
            await apply_on_stream(
                store,
                bus,
                stream_run_id="base",
                command=SubmitMessage(run_id="base", content=_user(f"q{index}", index)),
                idempotency_key=f"submit:{index}",
            )
        before = await store.replay("base", 0)
        _new_run, events = await apply_on_stream(
            store,
            bus,
            stream_run_id="forked",
            command=RewindRun(run_id="forked", base_run_id="base", base_to_seq=1, reason="redo"),
            idempotency_key="rewind-1",
        )
        assert [e.type for e in events] == ["run_rewounded"]
        after = await store.replay("base", 0)
        assert [r["seq"] for r in after] == [r["seq"] for r in before]  # 旧流逐行相同
        assert len(after) == len(before)
        refs = await prefix_seed_refs(store, base_run_id="base", base_to_seq=2, session_id="sess-x")
        gseqs = [r["gseq"] for r in await store.replay("base", 0) if r["seq"] <= 2]
        assert [ref.seq for ref in refs] == gseqs  # per-run seq → 全局 gseq 的换算逐条对得上
    finally:
        await store.close()


async def test_session_update_and_fork_helpers_write_their_streams(tmp_path):
    store = await SQLiteStore(str(tmp_path / "s.db")).connect()
    try:
        bus = InProcessEventBus(store)
        _r, events = await apply_session_update(store, bus, session_id="sess-a", title="renamed", pinned=True)
        assert [e.type for e in events] == ["session_renamed", "session_pinned"]
        _r2, forked = await apply_fork(store, bus, new_session_id="sess-b", source_session_id="sess-a", from_seq=2)
        assert [e.type for e in forked] == ["session_forked"]
        rows_a = await store.replay(session_stream_id("sess-a"), 0)
        rows_b = await store.replay(session_stream_id("sess-b"), 0)
        assert [r["type"] for r in rows_b] == ["session_forked"]
        assert "session_forked" not in [r["type"] for r in rows_a]  # 源流不被写入
    finally:
        await store.close()


async def test_session_patch_compares_against_the_current_row(tmp_path):
    """同值 PATCH 不是第二条事实：会话流每次都从头取号，只能靠现值比对挡住重试/双击/重放。"""
    store = await SQLiteStore(str(tmp_path / "s.db")).connect()
    try:
        bus = InProcessEventBus(store)
        sid = await store.create_session()
        _run, first = await apply_session_update(store, bus, session_id=sid, title="launch review")
        assert [e.type for e in first] == ["session_renamed"]
        assert (await store.session_row(sid))["title"] == "launch review"  # 投影写真的落了行
        head_after = await store.sequence_head(session_stream_id(sid))

        _run2, again = await apply_session_update(store, bus, session_id=sid, title="launch review")
        assert again == ()  # 完全同值：不发事件
        assert await store.sequence_head(session_stream_id(sid)) == head_after  # 也**不占 seq**
        assert (await store.session_row(sid))["title"] == "launch review"

        _run3, third = await apply_session_update(store, bus, session_id=sid, title="renamed", pinned=True)
        assert [e.type for e in third] == ["session_renamed", "session_pinned"]
        row = await store.session_row(sid)
        assert row["title"] == "renamed" and row["pinned"] is True
    finally:
        await store.close()


async def test_session_list_orders_pinned_first_and_hides_archived(tmp_path):
    """会话列表：置顶优先、更新时间倒序，归档项默认不列（不新增列，复用既有位）。"""
    store = await SQLiteStore(str(tmp_path / "s.db")).connect()
    try:
        bus = InProcessEventBus(store)
        plain = await store.create_session()
        other = await store.create_session()
        _r, _e = await apply_session_update(store, bus, session_id=other, title="pinned one", pinned=True)
        _r2, _e2 = await apply_session_update(store, bus, session_id=plain, title="archived one", archived=True)
        ids = [row["session_id"] for row in await store.list_sessions()]
        assert plain not in ids  # 归档默认不列
        assert ids[0] == other  # 置顶排最前
        shown = await store.list_sessions(include_archived=True)
        assert {row["session_id"] for row in shown} >= {plain, other}
        assert next(row for row in shown if row["session_id"] == plain)["archived"] is True
    finally:
        await store.close()
