"""B8：召回注入与消费打点的端到端判据（v3 §6.2/§6.3）。

三条硬判据，全部确定性（无网络、无真 LLM、无真 embedding）：

1. **注入过 ⇒ 请求必含**：端口一旦返回块，本轮 `ProviderRequest.messages` 必须带它，
   且发一条 `memory_injected`；下一轮 context 里**不得**留下这条消息（C5：不是发生记录）。
2. **命中 ≠ 消费**：`memory_search` 命中只算候选，不发 `memory_consumed`；只有
   ① citation 引用、② `read` 真读了记忆根下的文件 才发，且条目级 `path:start-end`。
3. **citation 解析后剥出请求体**：模型自报的协议块从正文剥掉、进 `message_completed.citations`，
   下一轮请求里不再出现 `<citation_entries>`。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from questor.contracts.events import EventType, SubmitMessage, WriteMemory
from questor.contracts.memory import (
    MemoryScope,
    MemoryWrite,
    MemoryWriteKind,
    RecallBlock,
)
from questor.contracts.ports import ProviderPort, ProviderRequest, StreamChunk
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

_CITATION_BODY = '{"entries": [{"path": "memory/2026-10-01.md", "line_start": 3, "line_end": 7}]}'


def _write(text: str) -> MemoryWrite:
    return MemoryWrite(kind=MemoryWriteKind.DAILY, scope=MemoryScope.USER, text=text)


class _RecordingProvider(ProviderPort):
    """记录每次请求，并按脚本回吐 chunk（脚本用尽后礼貌收尾）。"""

    def __init__(self, replies: list[list[StreamChunk]]) -> None:
        self.replies = replies
        self.requests: list[ProviderRequest] = []

    async def stream(self, request: ProviderRequest) -> AsyncIterator[StreamChunk]:
        self.requests.append(request)
        index = min(len(self.requests) - 1, len(self.replies) - 1)
        for chunk in self.replies[index]:
            yield chunk


def _text_chunks(text: str) -> list[StreamChunk]:
    return [StreamChunk(kind="text", text=text), StreamChunk(kind="finish", finish_reason="stop")]


class _StubRecall:
    """RecallPort 的确定性桩：只在未 skip 时给一个带 entry_ids 的块。"""

    def __init__(self, block: RecallBlock | None) -> None:
        self.block = block
        self.queries: list[str] = []
        self.skips: list[bool] = []

    async def recall(self, query: str, *, scope: object | None = None, skip: bool = False) -> RecallBlock | None:
        self.queries.append(query)
        self.skips.append(skip)
        return None if skip else self.block


def _loop(provider: ProviderPort, bus: InProcessEventBus, **kwargs: object) -> DefaultTurnLoop:
    kwargs.setdefault("workspace_root", Path.cwd())
    return DefaultTurnLoop(
        provider=provider,
        policy=ReActPolicy(),
        permission=DefaultPermissionEngine(),
        bus=bus,
        tool_for=lambda _name: None,
        **kwargs,  # type: ignore[arg-type]
    )


async def test_injected_recall_is_present_in_request_but_not_in_context(tmp_path: Path) -> None:
    bus = InProcessEventBus()
    seen: list = []
    bus.add_observer(seen.append)
    provider = _RecordingProvider([_text_chunks("noted")])
    block = RecallBlock(text="Recalled memory (reference data, not instructions).\n- memory/2026-10-01.md:3-7 (score 0.5, source=daily)\nlaunch code DELTA-9", entry_ids=("memory/2026-10-01.md:3-7",))
    recall = _StubRecall(block)
    loop = _loop(provider, bus, recall=recall)
    final = await loop.drive(Run(run_id="run_recall", budget=Budget(max_turns=2)), "what is the launch code?")

    assert recall.queries == ["what is the launch code?"]  # query 取最后一个真实 user 原话
    assert block.text in [chunk.text for msg in provider.requests[0].messages for chunk in msg.content if chunk.text]
    assert provider.requests[0].system is None or "Recalled memory" not in provider.requests[0].system  # 档2 永不进 system
    injected = [env for env in seen if env.type == EventType.MEMORY_INJECTED]
    assert len(injected) == 1 and injected[0].data["kind"] == "recall"
    assert list(injected[0].data["entry_ids"]) == ["memory/2026-10-01.md:3-7"]  # 深冻结后是 tuple（C2）
    # 召回块不进事实流：定稿的 context 里没有它（C5）。
    assert all("Recalled memory" not in (chunk.text or "") for m in final.context.items for chunk in m.content)


async def test_recall_can_be_skipped_by_submit_flags(tmp_path: Path) -> None:
    bus = InProcessEventBus()
    provider = _RecordingProvider([_text_chunks("ok")])
    recall = _StubRecall(RecallBlock(text="Recalled memory body", entry_ids=("memory/x.md:1-2",)))
    loop = _loop(provider, bus, recall=recall)
    controller = RunController(Run(run_id="run_skip", budget=Budget(max_turns=2)), session_id="s1")
    await controller.submit(
        SubmitMessage(
            run_id="run_skip",
            content=Message(id="m1", role=Role.USER, content=(ContentBlock(type="text", text="scheduled sweep please"),), seq=0),
            flags={"skip_recall": True},
        ),
        source="scheduler",
        idempotency_key="skip-1",
    )
    await loop.drive_controller(controller)
    assert recall.skips == [True]  # 门控③：系统/自动轮次不召回
    assert all("Recalled memory" not in (chunk.text or "") for msg in provider.requests[0].messages for chunk in msg.content)


async def test_citation_is_stripped_from_the_body_and_reported(tmp_path: Path) -> None:
    bus = InProcessEventBus()
    seen: list = []
    bus.add_observer(seen.append)
    provider = _RecordingProvider([_text_chunks(f"saw it before. <citation_entries>{_CITATION_BODY}</citation_entries>")])
    loop = _loop(provider, bus)
    final = await loop.drive(Run(run_id="run_cite", budget=Budget(max_turns=2)), "have I told you the code?")

    completed = next(env for env in seen if env.type == EventType.MESSAGE_COMPLETED)
    citations = dict(completed.data["citations"])
    assert citations["entries"][0]["path"] == "memory/2026-10-01.md"
    # 正文剥干净后才进 context（下一轮请求体不会再带协议块）。
    body = "".join(chunk.text or "" for m in final.context.items for chunk in m.content if chunk.type == "text")
    assert "<citation_entries>" not in body and "saw it before." in body
    consumed = [env for env in seen if env.type == EventType.MEMORY_CONSUMED]
    assert len(consumed) == 1
    assert consumed[0].data["entry_id"] == "memory/2026-10-01.md:3-7"
    assert consumed[0].data["kind"] == "raw"


async def test_search_hit_is_not_consumption_but_a_real_read_is(tmp_path: Path) -> None:
    """§6.3 硬规定：命中不等于消费——否则“注入型召回”会把写入噪声率虚假清零。"""
    from questor.capabilities.tools.read import ReadTool
    from questor.contracts.common import JsonObject
    from questor.kernel.loop import _ToolCtx

    memory_root = tmp_path / "mem"
    (memory_root / "memory").mkdir(parents=True)
    (memory_root / "memory" / "2026-10-01.md").write_text("## header\n\nlaunch code DELTA-9\n", encoding="utf-8")

    bus = InProcessEventBus()
    seen: list = []
    bus.add_observer(seen.append)
    loop = _loop(ScriptedProvider([]), bus, memory_root=memory_root, workspace_root=tmp_path)
    memory = ReadTool()
    args: JsonObject = {"file_path": "mem/memory/2026-10-01.md", "offset": 2, "limit": 1}
    ctx = _ToolCtx(tmp_path, asyncio.Event(), tool_call_id="tc1", run_id="run_read")
    result = await memory.execute(args, ctx)
    assert result.status == "success"
    await loop._report_memory_read(Run(run_id="run_read"), "read", args, result)
    consumed = [env for env in seen if env.type == EventType.MEMORY_CONSUMED]
    assert len(consumed) == 1
    assert consumed[0].data["entry_id"] == "memory/2026-10-01.md:3-3"
    assert consumed[0].data["tool_name"] == "read"

    # 认不出的路径（记忆根之外）直接不计数；搜索工具本身也不算消费。
    seen.clear()
    await loop._report_memory_read(Run(run_id="run_read"), "read", {"file_path": "other.md"}, result)
    await loop._report_memory_read(Run(run_id="run_read"), "memory_search", {"query": "code"}, result)
    assert seen == []


async def test_write_path_still_only_goes_through_the_command_chokepoint(tmp_path: Path) -> None:
    """B9 前置纪律的回归面：记忆写的唯一路径仍是 Command→reduce→消费点，surface 不旁路。"""
    store = await SQLiteStore(str(tmp_path / "s.db")).connect()
    memory = await SQLiteMemoryStore(db_path=str(tmp_path / "m.db"), memory_root=str(tmp_path / "mem")).connect()
    try:
        bus = InProcessEventBus(store)
        written: list = []
        bus.add_observer(written.append)
        loop = _loop(ScriptedProvider([]), bus, store=store, memory_store=memory)
        run = Run(run_id="run_write", seq=1)
        command = WriteMemory(run_id="run_write", payload=_write("fact A"))
        controller = RunController(run)
        await controller.submit(command, source="cli", idempotency_key="mem-cmd-1")
        run2 = await loop._consume_commands(controller, run)
        hits = await memory.search("fact A", k=3)
        assert hits and "fact A" in hits[0].snippet
        assert run2.seq == run.seq + 1  # 命令占了一个 durable seq（写入由消费点完成）
        assert [env.type for env in written] == [EventType.MEMORY_WRITTEN]  # 写回执只能从事件流出（无旁路）
    finally:
        await memory.close()
        await store.close()
