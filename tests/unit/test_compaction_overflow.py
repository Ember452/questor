"""B10 五道闸门里的 ①②③④（端到端可观察）+ 窗口代际 + 熔断跳闸。

判据都落在**后果**上：下一轮请求真的少了消息、事实流里原文一条没少、窗口身份逐代递增、
摘要器连交三次白卷后内核真的不再自动压。⑤（头部孤儿 property）在 `test_compaction_orphan.py`。

种上下文一律走 `loop._transition` + `_emit`（= 咽喉 + 总线），因为"事实流里一条不少"这句话
只有在事件真的进了 `event_log` 之后才可测——纯内存 reduce 的种数据不算事实流。
"""

from __future__ import annotations

from pathlib import Path

from questor.capabilities.tools._output import envelope_for_text
from questor.capabilities.tools.read import ReadTool
from questor.contracts.events import (
    AppendAssistantMessage,
    EventType,
    RecordToolResult,
    SubmitMessage,
)
from questor.contracts.policy import CompactionConfig
from questor.contracts.ports import StreamChunk
from questor.contracts.state_schema import Budget, ContentBlock, Message, Role
from questor.contracts.tool import ToolResult
from questor.kernel.compaction import MAX_CONSECUTIVE_COMPACT_FAILURES
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.kernel.run_control import RunController
from questor.policy.react_policy import ReActPolicy
from questor.providers.artifact_store import FileSystemArtifactStore
from questor.providers.fake import ScriptedProvider
from questor.providers.store_sqlite import SQLiteStore
from questor.state.checkpoint import closed_prefix, orphan_tool_result_ids
from questor.state.domain_state import Context, Run

_FINISH = [StreamChunk(kind="finish", finish_reason="stop")]
_CFG = CompactionConfig(keep_head=1, keep_tail=1, max_items=3)


def _user(text: str, seq: int) -> Message:
    return Message(id=f"u{seq}", role=Role.USER, content=(ContentBlock(type="text", text=text),), seq=seq)


def _assistant(text: str, seq: int) -> Message:
    return Message(id=f"a{seq}", role=Role.ASSISTANT, content=(ContentBlock(type="text", text=text),), seq=seq)


def _tool_use(call_id: str, seq: int) -> Message:
    return Message(
        id=f"m{seq}",
        role=Role.ASSISTANT,
        content=(ContentBlock(type="tool_use", tool_use_id=call_id, name="read", input={"f": "a"}),),
        seq=seq,
    )


class _RecordingProvider:
    """记请求、按 turn 回放脚本 chunk（闸门④的判据就在"请求里到底带了哪几条消息"）。"""

    def __init__(self) -> None:
        self.requests: list = []

    async def stream(self, request):  # noqa: ANN201 - duck-typed ProviderPort
        self.requests.append(request)
        for chunk in _FINISH:
            yield chunk


class _EmptySummarizer:
    """每次都交白卷的摘要器（真实故障形状：LLM 返回空/被截成空）。"""

    def __init__(self) -> None:
        self.calls = 0

    async def summarize(self, evicted, *, max_chars: int) -> str:  # noqa: ANN001
        self.calls += 1
        return ""


def _loop(
    tmp_path: Path,
    store: SQLiteStore,
    *,
    compaction: CompactionConfig | None,
    provider: object | None = None,
    summarizer: object | None = None,
) -> DefaultTurnLoop:
    return DefaultTurnLoop(
        provider=provider if provider is not None else ScriptedProvider([]),  # type: ignore[arg-type]
        policy=ReActPolicy(),
        permission=DefaultPermissionEngine(),
        bus=InProcessEventBus(store),
        tool_for=lambda name: {"read": ReadTool()}.get(name),
        tools=(),
        workspace_root=tmp_path,
        store=store,
        compaction=compaction,
        summarizer=summarizer,  # type: ignore[arg-type]
    )


async def _seed(tmp_path: Path, store: SQLiteStore, run_id: str, *, compaction: CompactionConfig | None = None) -> tuple[DefaultTurnLoop, Run]:
    """经咽喉种 6 条**全配对**消息（含一条 read 调用对 + 唯一事实 ORPHANCANARY），事件真落库。"""
    loop = _loop(tmp_path, store, compaction=compaction)
    run = Run(run_id=run_id, budget=Budget(max_turns=8), context=Context(items=()))
    steps = [
        SubmitMessage(run_id=run_id, content=_user("the code is ORPHANCANARY", 0)),
        AppendAssistantMessage(run_id=run_id, turn=1, message=_assistant("noted", 1)),
        AppendAssistantMessage(run_id=run_id, turn=1, message=_tool_use("tc1", 2)),
        RecordToolResult(run_id=run_id, tool_call_id="tc1", status="success", result="file body here"),
        AppendAssistantMessage(run_id=run_id, turn=2, message=_assistant("done reading", 3)),
        SubmitMessage(run_id=run_id, content=_user("thanks", 4)),
    ]
    for command in steps:
        run, events = await loop._transition(run, command)
        await loop._emit(events)
    return loop, run


async def test_fold_shrinks_the_next_request(tmp_path: Path) -> None:
    """闸门④：同一份上下文，折叠后的**下一轮请求消息数严格更少**（provider 侧可观察）。"""
    store = await SQLiteStore(":memory:").connect()
    try:
        plain_loop, plain_run = await _seed(tmp_path, store, "rstays", compaction=None)
        plain_provider = _RecordingProvider()
        plain_loop.provider = plain_provider
        await plain_loop.drive(plain_run, "follow-up")

        fold_loop, fold_run = await _seed(tmp_path, store, "rfold", compaction=_CFG)
        before = len(fold_run.context.items)
        folded = await fold_loop._maybe_compact(RunController(fold_run), fold_run, turn=3, total_tokens=999)
        assert len(folded.context.items) < before
        assert folded.context.summary  # 中段进摘要（不是凭空消失）

        fold_provider = _RecordingProvider()
        fold_loop.provider = fold_provider
        await fold_loop.drive(folded, "follow-up")

        assert plain_provider.requests and fold_provider.requests, "provider 未被调用"
        sent_plain = plain_provider.requests[0].messages
        sent_folded = fold_provider.requests[0].messages
        assert len(sent_folded) < len(sent_plain), f"折叠未减少下一轮请求：{len(sent_folded)} vs {len(sent_plain)}"
        # 折叠后的请求序列本身也不能带头部孤儿（闸门⑤在请求侧的同一判据）
        assert orphan_tool_result_ids(tuple(sent_folded)) == ()
    finally:
        await store.close()


async def test_folding_never_deletes_from_the_fact_stream(tmp_path: Path) -> None:
    """闸门③「只折叠不删除」：事实流里原文一条不少，且不存在任何删除型事件。"""
    store = await SQLiteStore(":memory:").connect()
    try:
        loop, run = await _seed(tmp_path, store, "rkeep", compaction=_CFG)
        folded = await loop._maybe_compact(RunController(run), run, turn=3, total_tokens=999)
        events = await store.replay("rkeep", 0)
        types = [e["type"] for e in events]
        assert EventType.COMPACT_APPLIED in types
        assert not any("deleted" in t or "removed" in t for t in types)  # 压缩不发删除
        # 逐出区的原文仍在 append-only 事实流里（被压的助手文本 + tool 结果 preview）。
        # 首条用户原话不在事件流里是 B1 既有口径（idle 首条由 run_started + 快照承载），不属本判据。
        blob = str([e.get("data") for e in events])
        assert "noted" in blob and "file body here" in blob
        # 同时在**活动上下文**里它已不在（这就是“折叠”：从请求里移出，但不是从事实里消失）
        assert not any("noted" in (block.text or "") for item in folded.context.items for block in item.content)
        applied = next(e for e in events if e["type"] == EventType.COMPACT_APPLIED)
        assert int(applied["data"]["evicted_count"]) >= 1
        # 上下文条目变少，但 seq 只增不减（折叠是**追加**了一条改写事实）
        assert len(folded.context.items) < len(run.context.items)
        assert folded.seq > run.seq
        assert closed_prefix(folded.context.items) == len(folded.context.items)  # 折叠后仍全闭合
    finally:
        await store.close()


async def test_window_identity_advances_per_generation(tmp_path: Path) -> None:
    """§7.1 窗口身份：从 `command_window`/事实流派生，**逐代递增并能回溯前一代**（零新表）。"""
    store = await SQLiteStore(":memory:").connect()
    try:
        loop, run = await _seed(tmp_path, store, "rwin", compaction=_CFG)
        first = await loop._maybe_compact(RunController(run), run, turn=3, total_tokens=999)
        identity = await store.window_identity("rwin")
        assert identity["window_number"] == 2  # 已压一代 → 下一次开的是 w2
        assert identity["previous_window_id"] == "rwin:w1"

        events = await store.replay("rwin", 0)
        applied = [e for e in events if e["type"] == EventType.COMPACT_APPLIED]
        payload = applied[-1]["data"]
        assert payload["window_id"] == "rwin:w1" and payload["window_number"] == 1
        assert payload["previous_window_id"] == "rwin:w0"  # 首代的"前一代"是原始窗口
        assert first.context.recovery_pointers  # 锚仍在（闸门②的读侧回由 test_compaction_recovery 覆盖）
    finally:
        await store.close()


async def test_breaker_trips_after_three_failed_folds(tmp_path: Path) -> None:
    """§7.3 熔断：摘要器连续交白卷 3 次 → 一条 durable `compact_warning`，之后**不再自动压**。"""
    store = await SQLiteStore(":memory:").connect()
    try:
        loop, run = await _seed(tmp_path, store, "rbreak", compaction=_CFG)
        bad = _EmptySummarizer()
        loop.summarizer = bad
        current = run
        for attempt in range(MAX_CONSECUTIVE_COMPACT_FAILURES):
            current = await loop._maybe_compact(RunController(current), current, turn=3, total_tokens=999)
            assert loop._compact_failures == attempt + 1
        assert bad.calls == MAX_CONSECUTIVE_COMPACT_FAILURES
        events = await store.replay("rbreak", 0)
        warnings = [e for e in events if e["type"] == EventType.COMPACT_WARNING]
        assert len(warnings) == 1
        assert warnings[0]["data"]["reason"] == "breaker_tripped"
        assert warnings[0]["data"]["failures"] == MAX_CONSECUTIVE_COMPACT_FAILURES
        # 跳闸后第四次：既不产新的 compact_started，也不再问摘要器（省钱判据就在这一步）
        started_before = len([e for e in events if e["type"] == EventType.COMPACT_STARTED])
        await loop._maybe_compact(RunController(current), current, turn=4, total_tokens=999)
        after = await store.replay("rbreak", 0)
        assert len([e for e in after if e["type"] == EventType.COMPACT_STARTED]) == started_before
        assert bad.calls == MAX_CONSECUTIVE_COMPACT_FAILURES
    finally:
        await store.close()


async def test_large_tool_output_is_archived_not_inlined(tmp_path: Path) -> None:
    """§7.2 C-1（BLK-10 收口）：超预算的工具输出进内容寻址 artifact，prompt 只留有界信封。"""
    store = await SQLiteStore(":memory:").connect()
    artifacts = FileSystemArtifactStore(tmp_path / "artifacts")
    await artifacts.connect()
    try:
        loop, run = await _seed(tmp_path, store, "rc1")
        loop.artifact_store = artifacts
        loop.output_envelope = envelope_for_text
        huge = ToolResult(status="success", result="L" * 40_000, display=None)
        wrapped = await loop._archive_output(run, "tc9", huge)
        assert isinstance(wrapped.result, dict)
        envelope = wrapped.result
        assert envelope["kind"] == "archived_tool_result"
        assert envelope["artifact_ref"]["artifact_id"]
        assert len(str(envelope["preview"]).encode("utf-8")) <= 16_384  # 进模型的只有有界 preview
        assert envelope["continuation"]["has_more"] is True
        # 小结果原样返回（未超预算不归档，行为逐字不变）
        small = ToolResult(status="success", result="tiny", display=None)
        assert await loop._archive_output(run, "tc10", small) is small
        # 未装 artifact_store 时也不归档（不新建第二条归档路径）
        loop.artifact_store = None
        assert await loop._archive_output(run, "tc11", huge) is huge
    finally:
        await artifacts.close()
        await store.close()
