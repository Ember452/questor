"""P4 记忆任务级回归网雏形（evals；P10 完整网前的必备最小集）。

端到端跑一条事实的完整生命周期：``WriteMemory`` → 检索命中 → ``deep_dream`` 固化进 core →
再检索仍命中。用 fake provider（非真 LLM，蒸馏质量 UNVERIFIED）+ 无 embedding（关键词降级）。"""

from __future__ import annotations

from pathlib import Path

from questor.contracts.memory import MemoryScope, MemoryWrite, MemoryWriteKind
from questor.memory.distill import DistillOutcome, deep_dream
from questor.providers.store_memory_sqlite import SQLiteMemoryStore


class _DeterministicDistiller:
    async def distill(self, core: str, dailies: list[str]) -> DistillOutcome:
        facts = sorted({line.strip() for chunk in dailies for line in chunk.splitlines() if line.strip() and not line.startswith("#")})
        return DistillOutcome(new_core="# MEMORY\n" + "".join(f"- {f}\n" for f in facts), dream="eval dream")


async def test_write_retrieve_distill_retrieve_pipeline(tmp_path: Path) -> None:
    store = await SQLiteMemoryStore(db_path=str(tmp_path / "m.db"), memory_root=str(tmp_path / "root")).connect()
    try:
        await store.write(
            MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.USER, text="the capital eval token is EVALCAP77"),
            idempotency_key="ev1",
        )
        await store.sync()
        assert await store.search("EVALCAP77", k=5)  # 写后可检索
        await deep_dream(store, _DeterministicDistiller(), lookback_days=7)  # 夜间蒸馏固化
        core = await store.read_memory_text("MEMORY.md")
        assert "EVALCAP77" in core  # core 真源含该事实
        assert await store.search("EVALCAP77", k=5)  # 再检索命中（回归网）
    finally:
        await store.close()
