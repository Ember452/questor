"""Deep Dream 离线蒸馏 + run 边界 flush 测（DoD②；ADR-0025；T13）。

用确定性 fake provider（非真 LLM，真蒸馏质量 UNVERIFIED）。钉死：(a) 重写 core 含萃取事实、
(b) 产梦境日记且 dreams 不进索引、(c) 同输入二次运行 no-op、(d) 空哨兵只删不编、flush 幂等。
"""

from __future__ import annotations

from pathlib import Path

from questor.contracts.memory import MemoryScope, MemoryWrite, MemoryWriteKind
from questor.memory.distill import DistillOutcome, deep_dream, flush_run_to_daily
from questor.providers.store_memory_sqlite import SQLiteMemoryStore


class _MergeProvider:
    """把 daily 里的非标题行去重合并进 core（模拟萃取/消歧），并产一句梦境。"""

    def __init__(self) -> None:
        self.calls = 0

    async def distill(self, core: str, dailies: list[str]) -> DistillOutcome:
        self.calls += 1
        facts = sorted({line.strip() for chunk in dailies for line in chunk.splitlines() if line.strip() and not line.startswith("#")})
        new_core = "# MEMORY\n" + "".join(f"- {f}\n" for f in facts)
        return DistillOutcome(new_core=new_core, dream="conned a diary line")


class _EmptyProvider:
    async def distill(self, core: str, dailies: list[str]) -> DistillOutcome:
        return DistillOutcome(new_core="无", dream="无")  # 空哨兵 → 无可萃取


async def _open(tmp_path: Path) -> SQLiteMemoryStore:
    return await SQLiteMemoryStore(db_path=str(tmp_path / "memory.db"), memory_root=str(tmp_path / "mstore")).connect()


async def test_deep_dream_rewrites_core_and_writes_dream_diary(tmp_path: Path) -> None:
    store = await _open(tmp_path)
    try:
        await store.write(MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.USER, text="user likes orchids"), idempotency_key="d1")
        await store.write(MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.USER, text="user lives in Osaka"), idempotency_key="d2")
        await store.sync()
        result = await deep_dream(store, _MergeProvider(), lookback_days=7)
        assert result["wrote"] is True
        core = await store.read_memory_text("MEMORY.md")
        assert "orchids" in core and "Osaka" in core  # (a) core 被原子重写、含萃取事实
        dreams = [p for p in await store.list_memory_paths() if p.startswith("memory/dreams/")]
        assert dreams and (await store.read_memory_text(dreams[0])).strip()  # (b) 梦境日记产出
        assert await store.search("conned a diary line", k=5) == ()  # dreams 不进检索索引
    finally:
        await store.close()


async def test_deep_dream_hash_dedup_second_run_is_noop(tmp_path: Path) -> None:
    store = await _open(tmp_path)
    try:
        await store.write(MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.USER, text="alpha daily fact"), idempotency_key="a1")
        await store.sync()
        provider = _MergeProvider()
        await deep_dream(store, provider, lookback_days=7)
        core_after_first = await store.read_memory_text("MEMORY.md")
        second = await deep_dream(store, provider, lookback_days=7)
        # (c) 同 daily 原料二次运行：write_memory_text 命中 ledger → core 未被改写、idempotent。
        assert second["idempotent"] is True
        assert await store.read_memory_text("MEMORY.md") == core_after_first
    finally:
        await store.close()


async def test_deep_dream_empty_sentinel_does_not_fabricate(tmp_path: Path) -> None:
    store = await _open(tmp_path)
    try:
        await store.write(MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.USER, text="ephemeral chatter"), idempotency_key="e1")
        await store.sync()
        result = await deep_dream(store, _EmptyProvider(), lookback_days=7)
        assert result["wrote"] is False and result["reason"] == "empty-sentinel"
        assert await store.read_memory_text("MEMORY.md") == ""  # (d) 只删不编：未杜撰 core
    finally:
        await store.close()


async def test_flush_run_to_daily_is_idempotent(tmp_path: Path) -> None:
    store = await _open(tmp_path)
    try:
        r1 = await flush_run_to_daily(store, summary_text="run summary: decided to use SQLite", run_id="run-9")
        assert r1["wrote"] is True
        r2 = await flush_run_to_daily(store, summary_text="run summary: decided to use SQLite", run_id="run-9")
        assert r2["idempotent"] is True
        daily_paths = [p for p in await store.list_memory_paths() if p.startswith("memory/2")]
        text = await store.read_memory_text(daily_paths[0])
        assert text.count("decided to use SQLite") == 1  # 重复 flush 不二次 append（claim-then-commit）
    finally:
        await store.close()
