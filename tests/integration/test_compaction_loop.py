"""P10 TA4/TA5（集成）—— loop 在安全点**真发** compact_applied（落 event_log 权威）+ L2' 蒸馏桥可检索。

承"字段存在≠接线存在"（ADR-0029 教训）：本测试驱动 `DefaultTurnLoop._maybe_compact`，断言压缩
不是纸面——① `compact_started/applied` 作为 durable 事件进了 store 账本（可 `replay` 读到）；
② 被压区浓缩经 distill 写进记忆、可被 `memory_search` 回读（DoD-A「不丢事实召回」的记忆侧证据）。
"""

from __future__ import annotations

from pathlib import Path

from questor.capabilities.tools.read import ReadTool
from questor.contracts.events import AppendAssistantMessage, EventType, SubmitMessage
from questor.contracts.policy import CompactionConfig
from questor.contracts.state_schema import Budget, ContentBlock, Message, Role
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.kernel.run_control import RunController
from questor.policy.react_policy import ReActPolicy
from questor.providers.fake import ScriptedProvider
from questor.providers.store_memory_sqlite import SQLiteMemoryStore
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import Run
from questor.state.reduce import reduce


def _user(text: str, seq: int) -> Message:
    return Message(id=f"u{seq}", role=Role.USER, content=(ContentBlock(type="text", text=text),), seq=seq)


def _assistant(text: str, seq: int) -> Message:
    return Message(id=f"a{seq}", role=Role.ASSISTANT, content=(ContentBlock(type="text", text=text),), seq=seq)


async def test_maybe_compact_persists_compact_applied_and_distills(tmp_path: Path) -> None:
    store = await SQLiteStore(":memory:").connect()
    mem = await SQLiteMemoryStore(db_path=str(tmp_path / "m.db"), memory_root=str(tmp_path / "root")).connect()
    try:
        read = ReadTool()
        loop = DefaultTurnLoop(
            provider=ScriptedProvider([]),
            policy=ReActPolicy(),
            permission=DefaultPermissionEngine(),
            bus=InProcessEventBus(store),
            tool_for=lambda n: {"read": read}.get(n),
            tools=(read,),
            workspace_root=tmp_path,
            store=store,
            memory_store=mem,
            compaction=CompactionConfig(keep_head=1, keep_tail=1, max_items=2),
        )
        # 种三条**全配对**、含唯一事实 EVALX 的上下文（中段 a1 携带事实，压后应进 summary→distill）
        run = Run(run_id="rc", budget=Budget(max_turns=5))
        run, _ = reduce(run, SubmitMessage(run_id="rc", content=_user("the code is EVALX", 0)))
        run, _ = reduce(run, AppendAssistantMessage(run_id="rc", turn=1, message=_assistant("noted EVALX", 1)))
        run, _ = reduce(run, SubmitMessage(run_id="rc", content=_user("thanks", 2)))
        controller = RunController(run)

        new_run = await loop._maybe_compact(controller, run, turn=3, total_tokens=5)

        # ① 压缩确实改变了 Domain_State（summary + 锚），且经 reduce 单写
        assert new_run.context.summary is not None
        assert new_run.context.recovery_pointers  # covered_hash 生产者已落
        assert len(new_run.context.items) < len(run.context.items)

        # ② compact_started/applied 作为 durable 事件真进了账本（可重放，非纸面）
        events = await store.replay("rc", 0)
        types = {e["type"] for e in events}
        assert EventType.COMPACT_STARTED in types
        assert EventType.COMPACT_APPLIED in types

        # ③ L2' 蒸馏桥：被压区浓缩写进记忆、可检索回读（DoD-A 记忆侧）
        await mem.sync()
        hits = await mem.search("EVALX", k=5)
        assert hits  # 压缩丢弃的事实经 distill→daily→检索仍可召回
    finally:
        await store.close()
        await mem.close()
