"""B10/§7.1–7.3 口径：绝对阈值是**算出来的**、预警/熔断是**说出来的**、窗口是**有代际的**。

这里全是纯判据 + reduce 判据（端到端三闸门见 `test_compaction_overflow.py`）。核心口径：
未配 `context_window` 就逐字退回旧信号（既有测试零改动）；配了就必须按 §7.1 的公式算，
并且**算不出可用窗口就拒绝配置**（fail-closed，不拿假窗口去截真上下文）。
"""

from __future__ import annotations

import pytest

from questor.contracts.common import new_id
from questor.contracts.events import (
    AppendAssistantMessage,
    CompactContext,
    EventType,
    SubmitMessage,
    WarnCompaction,
)
from questor.contracts.memory import RecoveryPointer
from questor.contracts.policy import COMPACTABLE_TOOLS, CompactionConfig
from questor.contracts.state_schema import Budget, ContentBlock, Message, Role
from questor.kernel.compaction import CLEARED_PLACEHOLDER, MAX_CONSECUTIVE_COMPACT_FAILURES, summarize
from questor.providers.fake import FakeSummarizer
from questor.providers.model_windows import UNKNOWN_WINDOW, ModelWindow, window_from_env, windows_for_model
from questor.state.domain_state import Context, Run
from questor.state.reduce import reduce

_CFG = CompactionConfig(context_window=200_000, max_output=8_192)


def test_absolute_thresholds_follow_the_formula() -> None:
    """EW = 200000 - min(8192, 20000) = 191808；三个阈值各自减自己的缓冲。"""
    assert _CFG.effective_window() == 191_808
    assert _CFG.auto_threshold() == 191_808 - 20_000  # max(摘要预留, 自动缓冲) = 20_000
    assert _CFG.manual_threshold() == 191_808 - 3_000
    assert _CFG.warning_threshold() == 191_808 - 26_000
    # 顺序即语义：预警早于自动、自动早于手动（手动更紧，留给摘要的空间更少）
    assert _CFG.warning_threshold() < _CFG.auto_threshold() < _CFG.manual_threshold() < _CFG.effective_window()


def test_unknown_max_output_still_deducts_the_full_reserve() -> None:
    """没给 max_output 时按摘要预留扣满——宁保守也不高估可用空间。"""
    no_max = CompactionConfig(context_window=100_000)
    assert no_max.effective_window() == 80_000
    assert no_max.auto_threshold() == 60_000


def test_no_window_means_no_absolute_threshold() -> None:
    """未配 `context_window` = 不知道窗口 → 绝对阈值一律 None（旧信号继续生效）。"""
    legacy = CompactionConfig(keep_head=1, keep_tail=1, max_items=24)
    assert legacy.effective_window() is None
    assert legacy.auto_threshold() is None
    assert legacy.warning_threshold() is None
    assert legacy.threshold("manual") is None


def test_window_too_small_to_be_useful_is_refused() -> None:
    """窗口小到算不出正阈值就**拒绝配置**（不猜、不静默退回）。"""
    with pytest.raises(ValueError, match="too small"):
        CompactionConfig(context_window=20_000)


def test_unknown_trigger_is_refused() -> None:
    """`threshold()` 的来路是闭集：未知来路直接拒（与配置非法值拒绝启动同口径）。"""
    with pytest.raises(ValueError, match="unknown compaction trigger"):
        _CFG.threshold("vibes")


def test_write_shaped_tools_are_not_compactable() -> None:
    """白名单口径写进 L0 词汇表：只读检索 + 受控 shell；写类与子 agent 报告不在其内。"""
    assert {"read", "grep", "ls", "bash"} <= set(COMPACTABLE_TOOLS)
    assert not {"write", "edit", "apply_patch", "delegate"} & set(COMPACTABLE_TOOLS)
    assert CompactionConfig().compactable() == COMPACTABLE_TOOLS
    assert CompactionConfig(compactable_tools=("read",)).compactable() == ("read",)


def test_model_windows_never_guesses_an_unknown_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """命中不到家族 = `UNKNOWN_WINDOW`（不猜窗口）；env 覆盖优先于查表。"""
    monkeypatch.delenv("QUESTOR_CONTEXT_WINDOW", raising=False)
    monkeypatch.delenv("QUESTOR_MAX_OUTPUT", raising=False)
    assert windows_for_model("some-new-model-9000") == UNKNOWN_WINDOW
    assert windows_for_model("openai/gpt-4o") == windows_for_model("gpt-4o")
    assert windows_for_model("claude-sonnet-4").context_window == 200_000
    monkeypatch.setenv("QUESTOR_CONTEXT_WINDOW", "131072")
    monkeypatch.setenv("QUESTOR_MAX_OUTPUT", "16384")
    assert window_from_env("unknown-model") == ModelWindow(context_window=131_072, max_output=16_384)


async def test_bounded_summaries_carry_a_visible_placeholder() -> None:
    """§7.2：逐出工具结果后摘要里必须留一句“这里曾有内容”，且长度有界（C18）。

    占位符文本在 L2 与 `providers/fake.py` 各写一份（为不让 providers 反向 import 内核），
    所以本用例同时跑两边并**逐字比较**——漂移会在这里红，而不是在两处各自错。"""
    evicted = (
        Message(id=new_id("msg"), role=Role.ASSISTANT, content=(ContentBlock(type="tool_result", tool_use_id="t1", text="x" * 9_000),), seq=0),
    )
    summary = summarize(evicted)
    assert CLEARED_PLACEHOLDER in summary
    assert len(summary) <= 4000
    fake = await FakeSummarizer().summarize(evicted, max_chars=4000)
    assert fake == summary  # 确定性 fake 与 L2 启发式逐字一致（回放/评测可复现的前提）


def _run() -> Run:
    run = Run(run_id="rw", budget=Budget(max_turns=5), context=Context(items=()))
    run, _ = reduce(run, SubmitMessage(run_id="rw", content=Message(id="u0", role=Role.USER, content=(ContentBlock(type="text", text="q1"),), seq=0)))
    run, _ = reduce(run, AppendAssistantMessage(run_id="rw", turn=1, message=Message(id="a1", role=Role.ASSISTANT, content=(ContentBlock(type="text", text="a1"),), seq=1)))
    run, _ = reduce(run, SubmitMessage(run_id="rw", content=Message(id="u2", role=Role.USER, content=(ContentBlock(type="text", text="q2"),), seq=2)))
    return run


def _pointer() -> tuple[RecoveryPointer, ...]:
    return (RecoveryPointer(seq_from=1, seq_to=1, covered_hash="sha256:abc"),)


def test_compact_events_carry_window_identity_and_trigger() -> None:
    """§7.1：compact 两条事件都带窗口身份/触发/信号源，`evicted_count` 由 reduce 算出。"""
    run = _run()
    new, events = reduce(
        run,
        CompactContext(
            run_id="rw",
            evict_start=1,
            evict_end=2,
            summary_text="folded",
            new_floor=2,
            new_pointers=_pointer(),
            trigger="auto",
            source="server_observed",
            window_id="rw:w1",
            previous_window_id="rw:w0",
            window_number=1,
            before_tokens=171_900,
        ),
    )
    started = next(env for env in events if env.type == EventType.COMPACT_STARTED)
    applied = next(env for env in events if env.type == EventType.COMPACT_APPLIED)
    assert started.data["window_id"] == "rw:w1" and started.data["trigger"] == "auto"
    assert applied.data["window_number"] == 1 and applied.data["previous_window_id"] == "rw:w0"
    assert applied.data["evicted_count"] == 1 and applied.data["before_tokens"] == 171_900
    assert applied.data["source"] == "server_observed"
    assert new.context.summary == "folded"


def test_compact_warning_is_one_durable_seq_and_changes_nothing() -> None:
    """§7.3：预警/熔断各自占一个 durable seq；**不改状态**（不静默，也不越权改上下文）。"""
    run = _run()
    items_before, seq_before = run.context.items, run.seq
    new, events = reduce(
        run,
        WarnCompaction(run_id="rw", turn=2, reason="pressure", trigger="auto", used_tokens=166_000, threshold=165_808, window_number=0, failures=0),
    )
    assert len(events) == 1 and events[0].type == EventType.COMPACT_WARNING
    assert dict(events[0].data) == {
        "reason": "pressure",
        "trigger": "auto",
        "used_tokens": 166_000,
        "threshold": 165_808,
        "window_number": 0,
        "failures": 0,
    }
    assert new.seq == seq_before + 1 and new.context.items == items_before


def test_compact_warning_reason_is_a_closed_enum() -> None:
    """自由文本不得进预警（正文不外发；面板只认闭集）。"""
    with pytest.raises(ValueError, match="must be one of"):
        WarnCompaction(run_id="rw", turn=1, reason="nearly out of context")


def test_breaker_limit_is_the_documented_three() -> None:
    """§7.3：熔断上限 3 是写进设计的数（上游事故数据背书），不是随手常量。"""
    assert MAX_CONSECUTIVE_COMPACT_FAILURES == 3
