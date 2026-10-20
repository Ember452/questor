"""B9/c5：写回八纪律逐条有测（v3 §6.4；§20 C-7 不建历史表）。

一条纪律一个测试，且**都落在可调用落点上**（不是文档承诺）：
配额闸 / 抽取预算 / 入站脱敏 / 媒体占位 / 归因位 / 软删+删除事件 / 硬过期 / 代际平行根。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from questor.contracts.events import DeleteMemory, EventType
from questor.contracts.memory import (
    MemoryScope,
    MemoryWrite,
    MemoryWriteKind,
)
from questor.contracts.state_schema import ContentBlock, Message, Role
from questor.kernel.events import InProcessEventBus
from questor.kernel.settle import TurnBoundary, TurnSettler
from questor.memory.consolidate import consolidate
from questor.memory.write_policy import (
    MAX_RECORD_BYTES,
    MEDIA_PLACEHOLDER,
    NOT_A_COMPLETE_HISTORY,
    TIER_RETENTION_DAYS,
    WritePolicy,
    bounded_extract,
    generation_root,
    prepare_write,
    quota_allows,
    redact_inbound,
    retention_expiry,
)
from questor.providers.store_memory_sqlite import SQLiteMemoryStore
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import Run
from questor.state.reduce import reduce


async def _query(store: SQLiteMemoryStore, sql: str, params: tuple = ()) -> list:
    """走 store 自己的连接读元数据（`sqlite3` 在仓内被 ruff banned，只允许 providers 用）。"""
    cur = await store._db.execute(sql, params)  # type: ignore[union-attr]
    return list(await cur.fetchall())


def _user(run_id: str, text: str) -> Message:
    return Message(id=f"m-{text}", role=Role.USER, content=(ContentBlock(type="text", text=text),), seq=0)


# ---- ① 配额闸 -------------------------------------------------------------- #
def test_quota_gate_blocks_low_remaining() -> None:
    assert quota_allows(None) is True  # 无配额来源 → 不启用该闸
    assert quota_allows(9) is False
    assert quota_allows(10) is True
    assert quota_allows(100) is True


async def test_consolidation_respects_quota_hold(tmp_path: Path) -> None:
    class _Never:
        async def distill(self, core, dailies):  # noqa: ANN001, ANN202
            raise AssertionError("配额不足时不得开工")

    store = await SQLiteMemoryStore(db_path=str(tmp_path / "m.db"), memory_root=str(tmp_path / "mem")).connect()
    try:
        outcome = await consolidate(store, _Never(), session_id="s1", remaining_percent=1)
        assert outcome.wrote is False and outcome.reason == "quota_hold" and outcome.attempts == 0
    finally:
        await store.close()


# ---- ② 抽取输入预算 -------------------------------------------------------- #
def test_extract_budget_keeps_newest_and_restores_source_order() -> None:
    items = [f"record-{index} {'x' * 50}" for index in range(20)]
    body, dropped = bounded_extract(items, budget_bytes=400)
    assert dropped > 0
    assert "record-19" in body and "record-0" not in body  # 保留最新
    lines = [line for line in body.splitlines() if line.startswith("record-")]
    numbers = [int(line.split("-")[1].split()[0]) for line in lines]
    assert numbers == sorted(numbers)  # 输出仍按源序，不倒着给模型
    assert NOT_A_COMPLETE_HISTORY in body  # 明写“不是完整历史、不得用作 resume”
    assert bounded_extract([], budget_bytes=100) == ("", 0)
    assert MAX_RECORD_BYTES > 0


# ---- ③ 入站脱敏 + ④ 媒体占位 + ⑤ 归因 + ⑦ 过期（写侧）--------------------- #
def test_inbound_redaction_and_media_placeholder_before_write() -> None:
    secret = "token: gho_abcdefghijklmnopqrstuvwxyz123456"
    assert "gho_abcdefghijklmnopqrstuvwxyz123456" not in redact_inbound(secret)
    prepared = prepare_write(
        'remember ![diagram](data:image/png;base64,AAAA) and the api_key="sk-abcdefghijklmnop"',
        policy=WritePolicy(attributed_to="user"),
    )
    assert MEDIA_PLACEHOLDER in prepared.text
    assert "sk-abcdefghijklmnop" not in prepared.text
    assert prepared.attributed_to == "user"
    assert prepared.text.strip()


def test_attribution_and_expiry_fields_are_validated() -> None:
    with pytest.raises(ValueError, match="attributed_to"):
        prepare_write("plain fact", policy=WritePolicy(attributed_to="wizard"))
    future = datetime.now(UTC) + timedelta(days=3)
    assert prepare_write("plain fact", expires_at=future).expires_at == future
    with pytest.raises(ValueError, match="timezone-aware"):
        prepare_write("plain fact", expires_at=datetime(2026, 1, 1))  # naive 拒收
    assert retention_expiry("dreams") is not None and retention_expiry("core") is None
    assert TIER_RETENTION_DAYS["daily"] == 180 and TIER_RETENTION_DAYS["sessions"] == 90


# ---- ⑥ 软删位 + 删除事件（不建历史表）------------------------------------- #
def test_delete_memory_produces_one_durable_event_and_no_state_history() -> None:
    run = Run(run_id="r-del", seq=1)
    command = DeleteMemory(run_id="r-del", entry_id="memory/2026-10-01.md:3-7", reason="user revoked")
    new, events = reduce(run, command)
    assert new.seq == run.seq + 1
    assert [env.type for env in events] == [EventType.MEMORY_DELETED]
    assert dict(events[0].data) == {"entry_id": "memory/2026-10-01.md:3-7", "reason": "user revoked"}
    # 撤回不往 context 里塞任何东西：变更史只有事件流一份（§20 C-7）。
    assert new.context.items == run.context.items
    with pytest.raises(ValueError, match="entry_id"):
        DeleteMemory(run_id="r", entry_id="   ")


async def test_revocation_is_a_soft_bit_replayable_and_creates_no_history_table(tmp_path: Path) -> None:
    store = await SQLiteMemoryStore(db_path=str(tmp_path / "m.db"), memory_root=str(tmp_path / "mem")).connect()
    await store.write(
        MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.USER, text="launch code DELTA-9", attributed_to="user"),
        idempotency_key="w1",
    )
    hits = await store.search("DELTA-9", k=3)
    assert hits
    entry_id = f"{hits[0].path}:{hits[0].start_line}-{hits[0].end_line}"
    receipt = await store.soft_delete(entry_id, idempotency_key="d1")
    assert receipt["removed"] == 1
    assert await store.search("DELTA-9", k=3) == ()  # 召回不再含该条
    again = await store.soft_delete(entry_id, idempotency_key="d2")
    assert again["removed"] == 0  # 幂等：已软删的行不会被二次命中
    source_file = Path(store.memory_root) / entry_id.split(":")[0]
    # 真源文件仍在（撤回是索引位，不是删事实）；且**没有 memory_history 表**（§20 C-7）。
    assert source_file.exists()
    tables = {row[0] for row in await _query(store, "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "memory_history" not in tables
    assert {"memory_chunks", "write_ledger"} <= tables
    flags = await _query(store, "SELECT is_deleted FROM memory_chunks WHERE path = ?", (entry_id.split(":")[0],))
    assert flags and all(row[0] == 1 for row in flags)
    await store.close()


async def test_sync_does_not_revive_revoked_memory(tmp_path: Path) -> None:
    """撤回后重建索引：软删位必须活下来（否则 wipe+rebuild 把已被否定的事实放回来）。"""
    store = await SQLiteMemoryStore(db_path=str(tmp_path / "m.db"), memory_root=str(tmp_path / "mem")).connect()
    try:
        await store.write(
            MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.USER, text="deprecated vendor is ACME"),
            idempotency_key="w2",
        )
        hits = await store.search("ACME", k=3)
        await store.soft_delete(f"{hits[0].path}:{hits[0].start_line}-{hits[0].end_line}", idempotency_key="d3")
        summary = await store.sync()
        assert summary["kept_deleted"] >= 1 and summary["revived"] == 0
        assert await store.search("ACME", k=3) == ()
    finally:
        await store.close()


# ---- ⑦ 硬过期与衰减分离 ---------------------------------------------------- #
async def test_expired_memory_leaves_search_while_decay_stays_scoring_only(tmp_path: Path) -> None:
    store = await SQLiteMemoryStore(db_path=str(tmp_path / "m.db"), memory_root=str(tmp_path / "mem")).connect()
    past = datetime.now(UTC) - timedelta(days=1)
    await store.write(
        MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.USER, text="stale fact about the old budget", expires_at=past),
        idempotency_key="exp-1",
    )
    await store.write(
        MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.USER, text="fresh fact about the old budget"),
        idempotency_key="exp-2",
    )
    hits = await store.search("old budget", k=5)
    texts = [hit.snippet for hit in hits]
    assert any("fresh fact" in text for text in texts)
    assert not any("stale fact" in text for text in texts)  # 过期直接退出，不靠排序
    assert all(hit.score > 0 for hit in hits)  # 衰减仍只作用于未过期条目
    await store.close()


# ---- ⑧ 代际平行根 ---------------------------------------------------------- #
def test_generation_roots_are_parallel_and_symlinks_are_refused(tmp_path: Path) -> None:
    base = tmp_path / "memory_store"
    assert generation_root(str(base), 1) == str(base)
    assert generation_root(str(base), 2) == f"{base}_v2"
    assert generation_root(str(base), 3) == f"{base}_v3"
    with pytest.raises(ValueError, match="generation must be >= 1"):
        generation_root(str(base), 0)
    link = tmp_path / "linked_root"
    try:
        link.symlink_to(tmp_path / "somewhere_else", target_is_directory=True)
    except OSError:  # Windows 无符号链接权限时只跳过本分支（上面的平行根判定已跑）
        pytest.skip("symlink creation not permitted on this host")
    with pytest.raises(ValueError, match="symlink"):
        generation_root(str(link), 1)


# ---- 记忆写只经 settle 回调（surface 不旁路）------------------------------ #
async def test_settle_write_path_carries_attribution_and_scope(tmp_path: Path) -> None:
    store = await SQLiteStore(str(tmp_path / "s.db")).connect()
    memory = await SQLiteMemoryStore(db_path=str(tmp_path / "m.db"), memory_root=str(tmp_path / "mem")).connect()
    try:
        bus = InProcessEventBus(store)
        events: list = []
        bus.add_observer(events.append)
        settler = TurnSettler(bus, store, memory, "s9")
        wrote = await settler.settle(
            TurnBoundary(
                run_id="run-s9",
                turn=1,
                user_text="the launch code is ZEPHYR-9",
                assistant_text="noted, ZEPHYR-9",
                interrupted=False,
                usage={},
            )
        )
        assert wrote is True
        written = [env for env in events if env.type == EventType.MEMORY_WRITTEN]
        assert written and written[0].run_id == "sess:s9"
        rows = await store.session_events("s9")
        assert any(row["type"] == "memory_written" for row in rows)
        hits = await memory.search("ZEPHYR-9", k=3)
        assert hits and hits[0].scope is MemoryScope.SESSION
        assert hits[0].attributed_to is None or hits[0].attributed_to in {"user", "assistant"}
    finally:
        await memory.close()
        await store.close()
