"""P10 Major-2（TDD RED→GREEN）—— covered_hash **回读 fail-closed 消费者**。

审计 Major-2 指出：`RecoveryPointer.matches()` 在 `src/` 零调用方、无按 `recovery_pointers`
从持久态回读原文 + 重算 `covered_hash` + 校验的执行路径——锚是"写-only"元数据，
"篡改→读回拒绝"（DoD-A①/ADR-0048）无兑现点。本测试钉住补齐后的行为：

1. 压缩后，`verify_recovery_anchors` 从 `pre_compact` 全量快照按锚索引切回原文、重算 hash、`matches()` 通过；
2. 篡改 `pre_compact` 快照里被覆盖区的消息（模拟历史被改写/分叉）→ **fail-closed 抛 AnchorIntegrityError**，绝不返旧内容。
"""

from __future__ import annotations

import json
from pathlib import Path

from questor.capabilities.tools.read import ReadTool
from questor.contracts.events import AppendAssistantMessage, SubmitMessage
from questor.contracts.policy import CompactionConfig
from questor.contracts.state_schema import Budget, ContentBlock, Message, Role, RunStatus
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.kernel.recovery import AnchorIntegrityError, verify_recovery_anchors
from questor.policy.react_policy import ReActPolicy
from questor.providers.fake import ScriptedProvider
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import Run
from questor.state.reduce import reduce


def _user(text: str, seq: int) -> Message:
    return Message(id=f"u{seq}", role=Role.USER, content=(ContentBlock(type="text", text=text),), seq=seq)


def _assistant(text: str, seq: int) -> Message:
    return Message(id=f"a{seq}", role=Role.ASSISTANT, content=(ContentBlock(type="text", text=text),), seq=seq)


async def _compact_a_run(store: SQLiteStore) -> Run:
    """装配带 store 的 loop、种全配对长上下文、在安全点压一次（pre_compact 快照随之落库）。"""
    read = ReadTool()
    loop = DefaultTurnLoop(
        provider=ScriptedProvider([]),
        policy=ReActPolicy(),
        permission=DefaultPermissionEngine(),
        bus=InProcessEventBus(store),
        tool_for=lambda n: {"read": read}.get(n),
        tools=(read,),
        workspace_root=Path.cwd(),
        store=store,
        compaction=CompactionConfig(keep_head=1, keep_tail=1, trigger_tokens=1),
    )
    run = Run(run_id="r_rec", budget=Budget(max_turns=5))
    run, _ = reduce(run, SubmitMessage(run_id="r_rec", content=_user("q1", 0)))
    run, _ = reduce(run, AppendAssistantMessage(run_id="r_rec", turn=1, message=_assistant("middle fact FOO", 1)))
    run, _ = reduce(run, SubmitMessage(run_id="r_rec", content=_user("q2", 2)))
    run, _ = reduce(run, AppendAssistantMessage(run_id="r_rec", turn=2, message=_assistant("a2", 3)))
    from questor.kernel.run_control import RunController

    controller = RunController(run)
    final = await loop._maybe_compact(controller, run, turn=3, total_tokens=999)
    # 持久化压缩后的当前态（含 recovery_pointers）为一个 auto checkpoint，供 verify 读锚
    await loop._checkpoint(final, "auto")
    assert final.status is not RunStatus.COMPLETED  # 未 finalize，仅压缩
    assert final.context.recovery_pointers
    return final


async def test_verify_recovers_covered_originals(tmp_path: Path) -> None:
    store = await SQLiteStore(str(tmp_path / "s.db")).connect()
    try:
        await _compact_a_run(store)
        recovered = await verify_recovery_anchors(store, "r_rec")
        # 回读到被压区原文（含中间那条 fact），且校验通过（无异常即 matches 成立）
        assert any("middle fact FOO" in ("".join(b.text or "" for b in m.content)) for m in recovered)
    finally:
        await store.close()


async def test_verify_fails_closed_on_tampered_history(tmp_path: Path) -> None:
    store = await SQLiteStore(str(tmp_path / "s.db")).connect()
    try:
        await _compact_a_run(store)
        # 篡改：把 pre_compact 快照里被覆盖区的消息原文改掉（模拟历史改写/分叉）
        cps = await store.checkpoints("r_rec")
        pre = next(cp for cp in cps if cp["kind"] == "pre_compact")
        payload = json.loads(pre["state_digest"])
        for msg in payload["items"]:
            for block in msg.get("content", []):
                if block.get("text") == "middle fact FOO":
                    block["text"] = "TAMPERED HISTORY"
        tampered = json.dumps(payload)
        await store._db.execute(  # noqa: SLF001 - 测试专用：直改落库快照模拟盘上分叉
            "UPDATE checkpoints SET state_digest = ? WHERE cp_id = ?", (tampered, pre["cp_id"])
        )
        await store._db.commit()  # noqa: SLF001

        import pytest

        with pytest.raises(AnchorIntegrityError):
            await verify_recovery_anchors(store, "r_rec")
    finally:
        await store.close()
