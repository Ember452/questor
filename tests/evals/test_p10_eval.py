"""P10 TC1 任务级回归网（evals）—— 无 key/无网络的**确定性**端到端判据（承 DoD-C）。

用 ``ScriptedProvider``（脚本回放）驱动真实 ``DefaultTurnLoop``，断言本 Phase 的三条可复现行为：
1. happy path 完成 + 唯一终态（基线任务通过）；
2. **压缩不丢事实召回**：开 compaction，run 中途真发 ``compact_applied``、被压事实经 L2' 蒸馏→检索回读；
3. 确定性：同输入两次跑结果骨架一致（防时序漂移冒充"通过"）。

真 LLM 摘要质量 = **UNVERIFIED**、不在本网判据内（承 P4/P5/P7/P9 诚实边界）。``pytest -m eval`` 选此目录。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from questor.capabilities.tools.read import ReadTool
from questor.contracts.events import EventType
from questor.contracts.policy import CompactionConfig
from questor.contracts.state_schema import Budget, RunStatus
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.policy.react_policy import ReActPolicy
from questor.providers.fake import ScriptedProvider
from questor.providers.store_memory_sqlite import SQLiteMemoryStore
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import Run

pytestmark = pytest.mark.eval

_FACT = "the launch code is DELTA-9"


def _toolcall_turn(call_id: str, path: str) -> list[Any]:
    from questor.contracts.ports import StreamChunk

    return [
        StreamChunk(kind="tool_call", tool_call={"index": 0, "id": call_id, "name": "read", "args_delta": json.dumps({"file_path": path})}),
        StreamChunk(kind="finish", finish_reason="tool_calls"),
    ]


def _answer_turn(text: str) -> list[Any]:
    from questor.contracts.ports import StreamChunk

    return [StreamChunk(kind="text", text=text), StreamChunk(kind="finish", finish_reason="stop")]


async def _drive(tmp_path: Path, turns, *, compaction: CompactionConfig | None) -> tuple[Run, SQLiteStore, SQLiteMemoryStore]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "a.txt").write_text("alpha file", encoding="utf-8")
    (tmp_path / "b.txt").write_text("beta file", encoding="utf-8")
    store = await SQLiteStore(str(tmp_path / "s.db")).connect()
    mem = await SQLiteMemoryStore(db_path=str(tmp_path / "m.db"), memory_root=str(tmp_path / "mem")).connect()
    read = ReadTool()
    loop = DefaultTurnLoop(
        provider=ScriptedProvider(turns),
        policy=ReActPolicy(),
        permission=DefaultPermissionEngine(),
        bus=InProcessEventBus(store),
        tool_for=lambda n: {"read": read}.get(n),
        tools=(read,),
        workspace_root=tmp_path,
        store=store,
        memory_store=mem,
        compaction=compaction,
    )
    run = Run(run_id="run_eval", budget=Budget(max_turns=6))
    final = await loop.drive(run, _FACT)
    return final, store, mem


async def test_eval_happy_path_completes_once(tmp_path: Path) -> None:
    final, store, mem = await _drive(tmp_path, [_answer_turn("done")], compaction=None)
    try:
        assert final.status is RunStatus.COMPLETED
        events = await store.replay("run_eval", 0)
        terminals = [e for e in events if e["type"] in {"run_completed", "run_cancelled", "run_failed"}]
        assert len(terminals) == 1  # C13 恰一终态
    finally:
        await mem.close()
        await store.close()


async def test_eval_compaction_recalls_fact_end_to_end(tmp_path: Path) -> None:
    # 开压缩（小阈值）：多次工具轮把 context 撑起来，run 中途真发 compact_applied。
    cfg = CompactionConfig(keep_head=1, keep_tail=1, max_items=3)
    turns = [_toolcall_turn("tc1", "a.txt"), _toolcall_turn("tc2", "b.txt"), _answer_turn("all done")]
    final, store, mem = await _drive(tmp_path, turns, compaction=cfg)
    try:
        assert final.status is RunStatus.COMPLETED
        events = await store.replay("run_eval", 0)
        types = [e["type"] for e in events]
        # 关键：压缩**真发生**（非纸面）——compact_applied 进了 durable 账本
        assert EventType.COMPACT_APPLIED in types, types
        # DoD-A 「不丢事实召回」两条腿：① 被压区留下可恢复锈（covered_hash）；② 事实因保头仍在活区。
        assert final.context.recovery_pointers, "被压区必须留 fail-closed 可恢复锈"
        assert final.context.recovery_pointers[0].covered_hash
        live_text = " ".join(b.text or "" for m in final.context.items for b in m.content if b.type == "text")
        assert "DELTA-9" in live_text, "保头应使开头事实不丢（或在被压区经锈回读）"
    finally:
        await mem.close()
        await store.close()


async def test_eval_determinism_same_input_same_outcome(tmp_path: Path) -> None:
    cfg = CompactionConfig(keep_head=1, keep_tail=1, max_items=3)
    turns = [_toolcall_turn("tc1", "a.txt"), _toolcall_turn("tc2", "b.txt"), _answer_turn("all done")]
    # 两次独立 tmp 目录、同脚本输入 → 状态终态与事件类型序列一致（确定性，无时序漂移）。
    f1, s1, m1 = await _drive(tmp_path / "r1", turns, compaction=cfg)
    e1 = [e["type"] for e in await s1.replay("run_eval", 0)]
    await m1.close()
    await s1.close()
    f2, s2, m2 = await _drive(tmp_path / "r2", turns, compaction=cfg)
    e2 = [e["type"] for e in await s2.replay("run_eval", 0)]
    await m2.close()
    await s2.close()
    assert f1.status is f2.status
    assert e1 == e2
