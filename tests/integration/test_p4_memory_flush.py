"""生产写触发器（审计 finding A 修复）：跑真实 ``CliSurface.run_once``（**非**手动 ``controller.submit``），
run 完成边界自动 episodic→daily flush → 新 store 实例检索命中。闭合"产品里记忆只能被读、无写触发器"。

用 ScriptedProvider（非真 LLM）；flush 是本地 sqlite + md 真源写，检索走关键词降级。"""

from __future__ import annotations

from pathlib import Path

from questor.contracts.ports import StreamChunk
from questor.providers.fake import ScriptedProvider
from questor.providers.store_memory_sqlite import SQLiteMemoryStore
from questor.surfaces.cli import CliSurface

_ANSWER = [
    StreamChunk(kind="text", text="the user's codename is ZEPHYR-9"),
    StreamChunk(kind="finish", finish_reason="stop"),
]


async def test_run_completion_flushes_daily_without_manual_write(tmp_path: Path) -> None:
    mem = await SQLiteMemoryStore(db_path=str(tmp_path / "m.db"), memory_root=str(tmp_path / "root")).connect()
    try:
        surface = CliSurface(workspace_root=tmp_path, provider=ScriptedProvider([_ANSWER]), memory_store=mem)
        # 只跑一轮正常对话，不手动发 WriteMemory——写由 run 完成边界 flush 自动产生。
        final = await surface.run_once("记住我的代号")
        assert final.status.value == "completed"

        daily = [p for p in await mem.list_memory_paths() if p.startswith("memory/2") and "/dreams/" not in p]
        joined = "".join([await mem.read_memory_text(p) for p in daily])
        assert "ZEPHYR-9" in joined  # md 真源含沉淀的最终回答

        hits = await mem.search("ZEPHYR-9", k=5)  # 检索命中（写→落库→检索，生产路径）
        assert hits and "ZEPHYR-9" in hits[0].snippet
    finally:
        await mem.close()


async def test_flush_is_idempotent_on_repeated_run_id(tmp_path: Path) -> None:
    # 同 run_id 二次 flush（如重投）不二次 append（claim-then-commit 幂等）。
    mem = await SQLiteMemoryStore(db_path=str(tmp_path / "m.db"), memory_root=str(tmp_path / "root")).connect()
    try:
        from questor.memory.distill import flush_run_to_daily

        first = await flush_run_to_daily(mem, summary_text="durable note ABC", run_id="run-x")
        second = await flush_run_to_daily(mem, summary_text="durable note ABC", run_id="run-x")
        assert first["wrote"] is True
        assert second["wrote"] is False and second["idempotent"] is True
    finally:
        await mem.close()
