"""B10 前置闸门⑤：压缩**绝不留头部孤儿 `tool_result`**（§7.2 缺陷 ⑤ / §13 B10）。

设计文档把这条列为"静态推导成立但未测"的项（§17 第 11 条 ③）。这里就是那条 property：
逐出后保留序列的**第一个**不能是一个没有 `tool_use` 的 `tool_result`——provider 强制配对，
命中即 4xx，且只在长会话出现、难复现。断言全部落在**可观察后果**（保留窗口里有没有孤儿），
不落在实现细节上。
"""

from __future__ import annotations

import pytest

from questor.contracts.common import new_id
from questor.contracts.events import AppendAssistantMessage, RecordToolResult, SubmitMessage
from questor.contracts.policy import CompactionConfig
from questor.contracts.state_schema import ContentBlock, Message, Role
from questor.kernel.compaction import legal_evict_end, plan_compaction
from questor.state.checkpoint import closed_prefix, open_tool_use_ids, orphan_tool_result_ids, tool_result_pairing
from questor.state.domain_state import Context, Run
from questor.state.reduce import reduce


def _user(text: str, seq: int) -> Message:
    return Message(id=new_id("msg"), role=Role.USER, content=(ContentBlock(type="text", text=text),), seq=seq)


def _assistant(text: str, seq: int) -> Message:
    return Message(id=new_id("msg"), role=Role.ASSISTANT, content=(ContentBlock(type="text", text=text),), seq=seq)


def _tool_use(call_id: str, seq: int, *, name: str = "read") -> Message:
    return Message(
        id=new_id("msg"),
        role=Role.ASSISTANT,
        content=(ContentBlock(type="tool_use", tool_use_id=call_id, name=name, input={"f": "a"}),),
        seq=seq,
    )


def _run_with(*commands: object) -> Run:
    """按序经 reduce 真建状态（不自造 ledger：工具名必须由 `AppendAssistantMessage` 登记）。"""
    run = Run(run_id=new_id("run"), context=Context(items=()))
    for command in commands:
        run, _events = reduce(run, command)  # type: ignore[arg-type]
    return run


#: §7.2 可见占位符（与 `kernel.compaction.CLEARED_PLACEHOLDER` 同源，本用例按字面钉住形状）。
CLEARED = "[Old tool result content cleared]"


def test_pairing_reports_both_directions() -> None:
    """`tool_result_pairing` 给双向集合；`closed_prefix` 只有单向（use 无 result）判据。"""
    items = (_tool_use("tc1", 0), _user("x", 1))
    used, produced = tool_result_pairing(items)
    assert used == {"tc1"} and produced == set()
    assert orphan_tool_result_ids(items) == ()  # 正向缺口不算孤儿
    reversed_items = (_user("x", 0), Message(id=new_id("msg"), role=Role.TOOL, content=(ContentBlock(type="tool_result", tool_use_id="tc1", text="out"),), seq=1))
    assert orphan_tool_result_ids(reversed_items) == ("tc1",)  # 反向失真被抓住


def test_head_orphan_case_is_stepped_back() -> None:
    """构造"下刀正好落在配对之间"的常规路径：`evict_end = n - keep_tail` 会把 result 切成头部孤儿。"""
    run = _run_with(
        SubmitMessage(run_id="r", content=_user("q1", 0)),
        AppendAssistantMessage(run_id="r", turn=1, message=_assistant("thinking", 1)),
        AppendAssistantMessage(run_id="r", turn=1, message=_tool_use("tc1", 2)),
        RecordToolResult(run_id="r", tool_call_id="tc1", status="success", result="file body"),
    )
    items = run.context.items
    assert len(items) == 4
    assert closed_prefix(items) == 4  # 全闭合：旧实现的 naive 右界就是 4-1=3
    cfg = CompactionConfig(keep_head=1, keep_tail=1, trigger_tokens=1)
    # naive 右界（不经 legal_evict_end）会造出孤儿——先把缺陷本身钉住
    assert orphan_tool_result_ids(items[1:1] + items[3:]) == ("tc1",)
    plan = plan_compaction(run, cfg, total_tokens=999)
    assert plan is not None
    assert plan.evict_end == 2  # 退一步：把 tool_use 留在保留区，配对不裂
    retained = items[: plan.evict_start] + items[plan.evict_end :]
    assert orphan_tool_result_ids(retained) == ()


@pytest.mark.parametrize("keep_head", [1, 2])
@pytest.mark.parametrize("keep_tail", [1, 2, 3])
def test_property_no_orphan_head_for_every_shape(keep_head: int, keep_tail: int) -> None:
    """property：任意头尾保护组合下，折叠后的保留序列都不带头部孤儿（闸门⑤）。"""
    run = _run_with(
        SubmitMessage(run_id="r", content=_user("q1", 0)),
        AppendAssistantMessage(run_id="r", turn=1, message=_assistant("a1", 1)),
        AppendAssistantMessage(run_id="r", turn=1, message=_tool_use("tc1", 2)),
        RecordToolResult(run_id="r", tool_call_id="tc1", status="success", result="body one"),
        AppendAssistantMessage(run_id="r", turn=2, message=_tool_use("tc2", 3)),
        RecordToolResult(run_id="r", tool_call_id="tc2", status="success", result="body two"),
        SubmitMessage(run_id="r", content=_user("q2", 4)),
        AppendAssistantMessage(run_id="r", turn=3, message=_assistant("a2", 5)),
    )
    cfg = CompactionConfig(keep_head=keep_head, keep_tail=keep_tail, trigger_tokens=1)
    plan = plan_compaction(run, cfg, total_tokens=9999)
    if plan is None:
        return  # 无安全窗口 = 保守不压，本身即合法结果
    retained = run.context.items[: plan.evict_start] + run.context.items[plan.evict_end :]
    assert orphan_tool_result_ids(retained) == ()
    assert plan.evict_end <= closed_prefix(run.context.items)  # C19 双向都守


def test_head_pair_split_does_not_leave_open_tool_use() -> None:
    """WF-003：keep_head 正好切在 tool_use 与其 result 之间时，头边界必须推进，
    保留头区不得留下悬空 tool_use（否则下一轮 provider 前 _ensure_paired_history 判失败）。"""
    run = _run_with(
        SubmitMessage(run_id="r", content=_user("q1", 0)),
        AppendAssistantMessage(run_id="r", turn=1, message=_tool_use("tc1", 1)),
        RecordToolResult(run_id="r", tool_call_id="tc1", status="success", result="body"),
        AppendAssistantMessage(run_id="r", turn=1, message=_assistant("a1", 2)),
        SubmitMessage(run_id="r", content=_user("q2", 3)),
        AppendAssistantMessage(run_id="r", turn=2, message=_assistant("a2", 4)),
    )
    items = run.context.items
    # 切在 keep_head=2：items[:2] = [user, tool_use(tc1)]——tc1 的 result 在 index 2（落在逐出窗）→头区悬空
    cfg = CompactionConfig(keep_head=2, keep_tail=1, trigger_tokens=1)
    plan = plan_compaction(run, cfg, total_tokens=9999)
    assert plan is not None, "此形状应能左界推进后安全压缩"
    assert plan.evict_start > 2, f"左界未推进，头区仍裂开 tc1：evict_start={plan.evict_start}"
    assert open_tool_use_ids(items[: plan.evict_start]) == ()


def test_nothing_safe_to_evict_returns_none() -> None:
    """退到无可退时返回 ``None``（不压），而不是硬造一个非法边界。"""
    run = _run_with(
        SubmitMessage(run_id="r", content=_user("q1", 0)),
        AppendAssistantMessage(run_id="r", turn=1, message=_tool_use("tc1", 1)),
        RecordToolResult(run_id="r", tool_call_id="tc1", status="success", result="only body"),
    )
    items = run.context.items
    # 唯一的配对正好横跨 keep_head 之后：legal_evict_end 只能退到 evict_start → 无中段
    assert legal_evict_end(items, evict_start=1, evict_end=2) == 1
    assert plan_compaction(run, CompactionConfig(keep_head=1, keep_tail=1, trigger_tokens=1), total_tokens=999) is None


def test_write_tool_result_is_never_evicted() -> None:
    """§7.2 白名单：写类工具（`write`）的结果不可重建，整段不压（read 结果在窗口内才被压）。"""
    run = _run_with(
        SubmitMessage(run_id="r", content=_user("q1", 0)),
        AppendAssistantMessage(run_id="r", turn=1, message=_tool_use("tc1", 1, name="write")),
        RecordToolResult(run_id="r", tool_call_id="tc1", status="success", result="wrote 42 lines"),
        AppendAssistantMessage(run_id="r", turn=1, message=_assistant("done", 2)),
        SubmitMessage(run_id="r", content=_user("q2", 3)),
    )
    cfg = CompactionConfig(keep_head=1, keep_tail=1, trigger_tokens=1)
    plan = plan_compaction(run, cfg, total_tokens=999)
    assert plan is None  # 白名单把右界收到 index 1 == evict_start → 无安全中段
    # 同一形状换成 read（白名单内）就能压，证明拒压的原因确实是白名单而不是配对
    run_read = _run_with(
        SubmitMessage(run_id="r", content=_user("q1", 0)),
        AppendAssistantMessage(run_id="r", turn=1, message=_tool_use("tc1", 1, name="read")),
        RecordToolResult(run_id="r", tool_call_id="tc1", status="success", result="read 42 lines"),
        AppendAssistantMessage(run_id="r", turn=1, message=_assistant("done", 2)),
        SubmitMessage(run_id="r", content=_user("q2", 3)),
    )
    read_plan = plan_compaction(run_read, cfg, total_tokens=999)
    assert read_plan is not None
    assert read_plan.evict_start == 1 and read_plan.evict_end >= 2
    assert CLEARED in read_plan.summary_text
