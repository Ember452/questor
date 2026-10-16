"""生产写触发器（审计 finding A 修复）：跑真实 ``CliSurface.run_once``（**非**手动 ``controller.submit``），
run 完成边界自动 episodic→daily flush → 新 store 实例检索命中。闭合"产品里记忆只能被读、无写触发器"。

用 ScriptedProvider（非真 LLM）；flush 是本地 sqlite + md 真源写，检索走关键词降级。"""

from __future__ import annotations

from pathlib import Path

from questor.contracts.common import new_id, utc_now
from questor.contracts.errors import ErrorEntry, ErrorKind, ErrorLayer, RecoveryHints
from questor.contracts.ports import StreamChunk
from questor.contracts.state_schema import ContentBlock, Message, Role, RunStatus
from questor.providers.fake import ScriptedProvider
from questor.providers.store_memory_sqlite import SQLiteMemoryStore
from questor.state.domain_state import Context, Run
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


def _assistant_run(status: RunStatus) -> Run:
    items = (Message(id=new_id("msg"), role=Role.ASSISTANT, content=(ContentBlock(type="text", text="final answer EPHEM-7"),), seq=0),)
    kw = {"run_id": "r-1", "status": status, "context": Context(items=items), "completed_at": utc_now()}
    if status is RunStatus.FAILED:
        kw["error_stack"] = (ErrorEntry(kind=ErrorKind.INTERNAL, layer=ErrorLayer.KERNEL, message="boom", at_turn=1, hints=RecoveryHints(), timestamp=utc_now()),)
    return Run(**kw)


async def test_flush_writes_on_completed_run(tmp_path: Path) -> None:
    mem = await SQLiteMemoryStore(db_path=str(tmp_path / "m.db"), memory_root=str(tmp_path / "root")).connect()
    try:
        surface = CliSurface(workspace_root=tmp_path, memory_store=mem)
        await surface._flush_run_to_daily(_assistant_run(RunStatus.COMPLETED))
        daily = [p for p in await mem.list_memory_paths() if p.startswith("memory/2")]
        texts = [await mem.read_memory_text(p) for p in daily]
        assert any("EPHEM-7" in t for t in texts)
    finally:
        await mem.close()


async def test_flush_skips_failed_run(tmp_path: Path) -> None:
    # failed/cancelled 的残缺输出不得污染长期记忆（链走发现：旧码在任意终态都 flush）。
    mem = await SQLiteMemoryStore(db_path=str(tmp_path / "m.db"), memory_root=str(tmp_path / "root")).connect()
    try:
        surface = CliSurface(workspace_root=tmp_path, memory_store=mem)
        await surface._flush_run_to_daily(_assistant_run(RunStatus.FAILED))
        daily = [p for p in await mem.list_memory_paths() if p.startswith("memory/2")]
        texts = [await mem.read_memory_text(p) for p in daily]
        assert not any("EPHEM-7" in t for t in texts)
    finally:
        await mem.close()
