"""P4 DoD①/⑤ 端到端集成（跨会话记住并检索到一件事）。

驱动一个**真实装配**的 turn loop（provider=ScriptedProvider、真实 SQLiteMemoryStore 注入）：
一个 run 里经 Command Inbox 提交 ``SubmitMessage`` + ``WriteMemory`` → 写必经 ``reduce`` 产
``memory_written`` → kernel 在消费点 sink 到 ``MemoryStorePort``（落 ``memory.db`` + md 真源）。
断言：① 同 store 立即可检索命中；② md 文件真源含标记；③ **记忆正文不进 ``Domain_State``**（DoD⑤）；
④ 新 store 实例（模拟新会话/跨进程，同 db + 同 md 根）仍能检索命中（跨会话记住）。

诚实边界：真 LLM 未用（ScriptedProvider 非真模型）；真 embedding 未用（无 embedding → 关键词降级）。"""

from __future__ import annotations

from pathlib import Path

from questor.contracts.common import new_id
from questor.contracts.events import SubmitMessage, WriteMemory
from questor.contracts.memory import MemoryScope, MemoryWrite, MemoryWriteKind
from questor.contracts.ports import StreamChunk
from questor.contracts.state_schema import Budget, ContentBlock, Message, Role
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.kernel.run_control import RunController
from questor.policy.react_policy import ReActPolicy
from questor.providers.fake import ScriptedProvider
from questor.providers.store_memory_sqlite import SQLiteMemoryStore
from questor.state.domain_state import Run

_MARKER = "BLUE-ORCHID-42"
_ANSWER = [StreamChunk(kind="text", text="noted"), StreamChunk(kind="finish", finish_reason="stop")]


async def _open_store(tmp_path: Path) -> SQLiteMemoryStore:
    return await SQLiteMemoryStore(db_path=str(tmp_path / "memory.db"), memory_root=str(tmp_path / "mstore")).connect()


async def test_dod1_write_persists_and_readback_cross_session(tmp_path: Path) -> None:
    store = await _open_store(tmp_path)
    run_id = new_id("run")
    try:
        loop = DefaultTurnLoop(
            provider=ScriptedProvider([_ANSWER]),
            policy=ReActPolicy(),
            permission=DefaultPermissionEngine(),
            bus=InProcessEventBus(None),
            tool_for=lambda name: None,
            memory_store=store,
            workspace_root=tmp_path,
        )
        controller = RunController(Run(run_id=run_id, budget=Budget(max_turns=3)))
        user_msg = Message(id=new_id("msg"), role=Role.USER, content=(ContentBlock(type="text", text="please remember this"),), seq=0)
        await controller.submit(SubmitMessage(run_id=run_id, content=user_msg), source="test", idempotency_key="submit")
        await controller.submit(
            WriteMemory(run_id=run_id, payload=MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.USER, text=f"my favorite code is {_MARKER}")),
            source="test",
            idempotency_key="mem-1",
        )
        final = await loop.drive_controller(controller)

        # DoD① — 同 store 立即可检索
        hits = await store.search(_MARKER, k=5)
        assert hits and _MARKER in hits[0].snippet
        # md 文件真源落盘
        daily_paths = [p for p in await store.list_memory_paths() if p.startswith("memory/")]
        joined = "".join([await store.read_memory_text(p) for p in daily_paths])
        assert _MARKER in joined
        # DoD⑤ — 记忆正文绝不进 Domain_State（只有 SubmitMessage 的用户文本在 items 里）
        assert all(_MARKER not in str(m.content) for m in final.context.items)
    finally:
        await store.close()

    # DoD① — 新会话/跨进程：另开 store 实例（同 memory.db + 同 md 根）仍能命中
    reopened = await _open_store(tmp_path)
    try:
        again = await reopened.search(_MARKER, k=5)
        assert again and _MARKER in again[0].snippet
    finally:
        await reopened.close()
