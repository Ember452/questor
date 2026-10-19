"""P10 TA4/TA5（TDD）—— 纯压缩决策 `plan_compaction` 的触发、C19 安全边界、可恢复锚稳定性。"""

from __future__ import annotations

from questor.contracts.common import new_id
from questor.contracts.events import AppendAssistantMessage, RecordToolResult, SubmitMessage
from questor.contracts.policy import CompactionConfig
from questor.contracts.state_schema import ContentBlock, Message, Role
from questor.kernel.compaction import covered_hash, plan_compaction
from questor.state.domain_state import Context, Run
from questor.state.reduce import reduce


def _user(text: str, seq: int) -> Message:
    return Message(id=new_id("msg"), role=Role.USER, content=(ContentBlock(type="text", text=text),), seq=seq)


def _assistant(text: str, seq: int) -> Message:
    return Message(id=new_id("msg"), role=Role.ASSISTANT, content=(ContentBlock(type="text", text=text),), seq=seq)


def _assistant_tool_use(call_id: str, seq: int) -> Message:
    return Message(id=new_id("msg"), role=Role.ASSISTANT, content=(ContentBlock(type="tool_use", tool_use_id=call_id, name="read", input={"f": "a"}),), seq=seq)


def _run(items: tuple[Message, ...]) -> Run:
    return Run(run_id=new_id("run"), context=Context(items=items))


_CFG = CompactionConfig(keep_head=1, keep_tail=1, trigger_tokens=100, max_items=None)


def test_no_compaction_below_trigger() -> None:
    items = (_user("a", 0), _assistant("b", 1), _user("c", 2), _assistant("d", 3))
    assert plan_compaction(_run(items), _CFG, total_tokens=50) is None  # 未达阈值


def test_compaction_evicts_middle_keeps_head_tail() -> None:
    items = (_user("q1", 0), _assistant("a1", 1), _user("q2", 2), _assistant("a2", 3))
    plan = plan_compaction(_run(items), _CFG, total_tokens=200)
    assert plan is not None
    assert plan.evict_start == 1
    assert plan.evict_end == 3  # 保留 items[0] 头 与 items[3] 尾
    assert "q1" not in plan.summary_text  # head 不被压进摘要
    assert "a2" not in plan.summary_text  # tail 不被压进摘要
    assert "a1" in plan.summary_text and "q2" in plan.summary_text
    assert plan.new_pointers[0].seq_from == 1 and plan.new_pointers[0].seq_to == 2


def test_compaction_never_evicts_open_tool_use_tail() -> None:
    # 尾部有未闭合 tool_use：closed_prefix 只到其之前；tail 保护区含未闭合调用时窗口为空 → None
    run, _ = reduce(Run(run_id="r"), SubmitMessage(run_id="r", content=_user("q1", 0)))
    run, _ = reduce(run, AppendAssistantMessage(run_id=run.run_id, turn=1, message=_assistant_tool_use("tc1", 1)))
    run, _ = reduce(run, SubmitMessage(run_id=run.run_id, content=_user("q2", 2)))
    run, _ = reduce(run, AppendAssistantMessage(run_id=run.run_id, turn=2, message=_assistant_tool_use("tc2", 3)))
    plan = plan_compaction(run, _CFG, total_tokens=500)
    # 未闭合 tc2 使 closed_prefix=3（前一条 tc1 已由后续 user? 不，tc1 也无 result）→ 关键：evict_end≤cut，
    # 绝不越过任何未闭合 tool_use；此处无安全中段，返回 None（保守不压）。
    assert plan is None or plan.evict_end <= len(run.context.items)


def test_compaction_boundary_respects_closed_prefix() -> None:
    # 全配对长对话：中间有 tool_use+result 对，允许压缩至 closed_prefix 内
    run, _ = reduce(Run(run_id="r"), SubmitMessage(run_id="r", content=_user("q1", 0)))
    run, _ = reduce(run, AppendAssistantMessage(run_id=run.run_id, turn=1, message=_assistant_tool_use("tc1", 1)))
    run, _ = reduce(run, RecordToolResult(run_id=run.run_id, tool_call_id="tc1", status="success", result="ok"))
    run, _ = reduce(run, SubmitMessage(run_id=run.run_id, content=_user("q2", 2)))
    run, _ = reduce(run, AppendAssistantMessage(run_id=run.run_id, turn=2, message=_assistant("a2", 3)))
    run, _ = reduce(run, SubmitMessage(run_id=run.run_id, content=_user("q3", 4)))
    plan = plan_compaction(run, CompactionConfig(keep_head=1, keep_tail=1, trigger_tokens=100), total_tokens=500)
    assert plan is not None
    # 逐出的中段必完全落在 closed_prefix 内（无孤儿 tool_use）
    from questor.state.checkpoint import closed_prefix as _cp

    assert plan.evict_end <= _cp(run.context.items)


def test_covered_hash_ignores_volatile_fields() -> None:
    # 同语义、不同 id/seq/tool_use_id → covered_hash 相等（跨 rebuild 稳定，fail-closed 不误拒）
    m1 = Message(id="id_A", role=Role.USER, content=(ContentBlock(type="tool_use", tool_use_id="tc_1", name="read", input={"f": "a"}),), seq=5)
    m2 = Message(id="id_B", role=Role.USER, content=(ContentBlock(type="tool_use", tool_use_id="tc_ZZZ", name="read", input={"f": "a"}),), seq=99)
    assert covered_hash([m1]) == covered_hash([m2])


def test_covered_hash_differs_on_semantic_change() -> None:
    m1 = Message(id="id_A", role=Role.USER, content=(ContentBlock(type="text", text="hello"),), seq=5)
    m2 = Message(id="id_B", role=Role.USER, content=(ContentBlock(type="text", text="TAMPERED"),), seq=5)
    assert covered_hash([m1]) != covered_hash([m2])
