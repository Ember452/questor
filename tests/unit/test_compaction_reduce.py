"""P10 TA1（TDD RED）—— ``reduce`` 对 ``CompactContext`` 的纯应用与压缩不变式。

覆盖 ADR-0048：① 压缩必经 Command→reduce、纯应用 loop 侧携带的 summary/锚（reduce 不算）；
② C19 绝不孤儿化 open tool_use（evict 边界须 ≤ ``closed_prefix``）；③ summary/covered_hash 非空
fail-closed；④ MAJ-8 纯函数性（同一命令两次 reduce 结果逐字相等）；⑤ 发 compact_started/applied
+ baseline_seq 栅栏（additive、无正文，C18/C20）。
"""

from __future__ import annotations

from dataclasses import replace

from questor.contracts.common import new_id
from questor.contracts.events import (
    AppendAssistantMessage,
    CompactContext,
    EventType,
    RecordToolResult,
    SubmitMessage,
)
from questor.contracts.memory import RecoveryPointer
from questor.contracts.state_schema import ContentBlock, Message, Role
from questor.state.domain_state import Run
from questor.state.reduce import reduce
from questor.state.snapshot import to_snapshot


def _run() -> Run:
    return Run(run_id=new_id("run"))


def _user(text: str, seq: int) -> Message:
    return Message(id=new_id("msg"), role=Role.USER, content=(ContentBlock(type="text", text=text),), seq=seq)


def _assistant_text(text: str, seq: int) -> Message:
    return Message(id=new_id("msg"), role=Role.ASSISTANT, content=(ContentBlock(type="text", text=text),), seq=seq)


def _assistant_tool_use(call_id: str, seq: int) -> Message:
    return Message(
        id=new_id("msg"),
        role=Role.ASSISTANT,
        content=(ContentBlock(type="tool_use", tool_use_id=call_id, name="read", input={"file_path": "a"}),),
        seq=seq,
    )


def _paired_run() -> Run:
    """四个全配对消息：user, assistant(tool_use tc1)+tool_result, user, assistant(text)。

    closed_prefix == 全部（无 open tool_use），中段可安全压缩。
    """
    run, _ = reduce(_run(), SubmitMessage(run_id="r", content=_user("q1", 0)))
    run, _ = reduce(run, AppendAssistantMessage(run_id=run.run_id, turn=1, message=_assistant_tool_use("tc1", 1)))
    run, _ = reduce(run, RecordToolResult(run_id=run.run_id, tool_call_id="tc1", status="success", result="ok"))
    run, _ = reduce(run, SubmitMessage(run_id=run.run_id, content=_user("q2", 2)))
    run, _ = reduce(run, AppendAssistantMessage(run_id=run.run_id, turn=2, message=_assistant_text("a2", 3)))
    return run


def _ptr() -> RecoveryPointer:
    return RecoveryPointer(seq_from=1, seq_to=2, covered_hash="sha256:deadbeef")


def test_compact_applies_summary_and_appends_anchor() -> None:
    run = _paired_run()
    n_items = len(run.context.items)
    assert n_items >= 3  # user, (tool_use/tool_result), user, assistant
    evict_start, evict_end = 1, n_items - 1  # 逐出中段、保头保尾，closed_prefix==n_items 故合法
    new, events = reduce(
        run,
        CompactContext(
            run_id=run.run_id,
            evict_start=evict_start,
            evict_end=evict_end,
            summary_text="summarized middle",
            new_floor=evict_end,
            new_pointers=(_ptr(),),
        ),
    )
    assert new.context.summary == "summarized middle"
    assert new.context.compaction_floor == evict_end
    assert new.context.recovery_pointers == (_ptr(),)
    assert len(new.context.items) == n_items - (evict_end - evict_start)  # 头尾保留
    types = [e.type for e in events]
    assert types == [EventType.COMPACT_STARTED, EventType.COMPACT_APPLIED]
    applied = events[-1].data
    assert applied["baseline_seq"] == events[-1].seq
    assert applied["covered_from"] == 1 and applied["covered_to"] == 2
    assert applied["summary_bytes"] == len(b"summarized middle")
    # 事件帧无正文（C20/D4）：只有关联/有界量，绝无 summary_text 原文
    assert "summary_text" not in applied


def test_compact_never_orphans_open_tool_use() -> None:
    # 尾部有未闭合 tool_use：closed_prefix 只到其之前，evict 越界必须被拒
    run, _ = reduce(_run(), SubmitMessage(run_id="r", content=_user("q1", 0)))
    run, _ = reduce(run, AppendAssistantMessage(run_id=run.run_id, turn=1, message=_assistant_tool_use("tc1", 1)))
    new, events = reduce(
        run,
        CompactContext(run_id=run.run_id, evict_start=0, evict_end=2, summary_text="x", new_floor=2, new_pointers=(_ptr(),)),
    )
    assert new.context.items == run.context.items  # 状态不变
    assert events[-1].type == EventType.WARNING  # 拒绝、出声、不崩


def test_compact_boundary_at_closed_prefix_is_allowed() -> None:
    # evict_end == closed_prefix（=1）：只逐出已配对的 user，允许
    run, _ = reduce(_run(), SubmitMessage(run_id="r", content=_user("q1", 0)))
    run, _ = reduce(run, AppendAssistantMessage(run_id=run.run_id, turn=1, message=_assistant_tool_use("tc1", 1)))
    new, events = reduce(
        run,
        CompactContext(run_id=run.run_id, evict_start=0, evict_end=1, summary_text="q1 recapped", new_floor=1, new_pointers=(_ptr(),)),
    )
    assert new.context.summary == "q1 recapped"
    assert [e.type for e in events] == [EventType.COMPACT_STARTED, EventType.COMPACT_APPLIED]


def test_compact_requires_non_empty_summary_and_hash() -> None:
    run = _paired_run()
    n_items = len(run.context.items)
    # 空 summary → reduce 拒绝（即便 __post_init__ 允许，reduce 也须 fail-closed）
    new, events = reduce(
        run,
        CompactContext(run_id=run.run_id, evict_start=1, evict_end=n_items - 1, summary_text="   ", new_floor=n_items - 1, new_pointers=(_ptr(),)),
    )
    assert new.context.summary is None
    assert events[-1].type == EventType.WARNING


def test_compact_reduce_is_pure_and_deterministic() -> None:
    """MAJ-8：同一 CompactContext 对同一原始 run 两次 reduce → 逐字相等的 Domain_State。"""
    run = _paired_run()
    n_items = len(run.context.items)
    cmd = CompactContext(run_id=run.run_id, evict_start=1, evict_end=n_items - 1, summary_text="s", new_floor=n_items - 1, new_pointers=(_ptr(),))
    n1, _ = reduce(run, cmd)
    n2, _ = reduce(run, replace(cmd, evict_start=1))  # 等价命令
    assert to_snapshot(n1) == to_snapshot(n2)
