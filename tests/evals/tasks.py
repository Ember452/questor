"""B12 · G 评测环的任务集（10 个：无网络、无真 LLM、可复现）。

形状照 wuu `evalharness/trace.go` 的"任务 = 输入 + 允许工具 + 判分器 + trace 形状"四件来，
但**判据全部落在 durable 事实上**（事件流 + Domain_State），不看模型说得好不好。

刻意包含三条"防自证"任务：撤销（`memory_deleted`）、幂等重复写（第二条不产新 seq）、
大输出归档（prompt 里只该有有界 preview）——这三条都是指标口径本身依赖的入口。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: 供任务标注的"应被记住"的事实（人工标，不是启发式猜——§10 遗忘率的唯一合法分母来源）。
FACT_LAUNCH = "the launch code is DELTA-9"
FACT_VENDOR = "the vendor contact is ACME-CORP-77"


@dataclass(frozen=True, slots=True)
class EvalTask:
    """一个评测任务：输入、允许工具集、provider 脚本、判据声明。"""

    id: str
    summary: str
    prompt: str
    turns: tuple[str, ...]
    tools: tuple[str, ...] = ("read",)
    compaction: str = ""  # "" | "tiny"（max_items=3）| "small"（max_items=6）
    post: tuple[str, ...] = ()  # 驱动后的附加步骤名（runner 解释）
    expect_types: tuple[str, ...] = ()  # 轨迹 shape：这些事件类型必须**按序**出现
    forbidden_types: tuple[str, ...] = ()
    terminal: str = "run_completed"
    must_close_pairs: bool = True
    expect_citations: bool = False
    expect_window_id: bool = False
    expect_archived: bool = False
    expect_written_count: int | None = None
    expect_idempotent_write: bool = False
    expected_facts: tuple[str, ...] = ()


TASKS: tuple[EvalTask, ...] = (
    EvalTask(
        id="answer-only",
        summary="纯文本回答：恰一终态、配对闭合、无工具轮",
        prompt="say done",
        turns=("answer:done",),
        expect_types=("run_started", "message_completed", "run_completed"),
    ),
    EvalTask(
        id="read-roundtrip",
        summary="一次 read 调用：tool_started/tool_completed 成对且顺序正确",
        prompt="read a.txt",
        turns=("read:tc1:a.txt", "answer:read it"),
        expect_types=("tool_started", "tool_completed", "message_completed", "run_completed"),
    ),
    EvalTask(
        id="two-tool-roundtrip",
        summary="两次工具轮：两对配对全部闭合（C19）",
        prompt="read both files",
        turns=("read:tc1:a.txt", "read:tc2:b.txt", "answer:both"),
        expect_types=("tool_started", "tool_completed", "run_completed"),
    ),
    EvalTask(
        id="unknown-tool-recovers",
        summary="模型建议不存在的工具：内核结构化报错闭合配对，run 不崩",
        prompt="call a tool that does not exist",
        turns=("unknown:tc9", "answer:recovered"),
        # 不存在的工具不会发 tool_started（在建计就拒），但必须闭合一条 tool_completed(status=error)
        expect_types=("tool_completed", "run_completed"),
    ),
    EvalTask(
        id="memory-write-and-recall",
        summary="写记忆 → 检索回读（遗忘率的数据面：应记的必须真在库里）",
        prompt=FACT_LAUNCH,
        turns=("answer:noted",),
        post=("write_memory",),
        expect_types=("message_completed", "memory_written"),
        expected_facts=(FACT_LAUNCH,),
    ),
    EvalTask(
        id="memory-revoke",
        summary="撤回一条记忆：durable `memory_deleted`，且不建历史表",
        prompt=FACT_VENDOR,
        turns=("answer:noted",),
        post=("write_memory", "delete_written"),
        expect_types=("memory_written", "memory_deleted"),
        expect_written_count=1,
    ),
    EvalTask(
        id="citation-stripped-from-body",
        summary="模型自报引用：协议块被剥出正文、只挂到 message_completed.citations",
        prompt="which note said so?",
        turns=("citation:see the note",),
        expect_types=("message_completed", "run_completed"),
        expect_citations=True,
    ),
    EvalTask(
        id="compaction-fold-with-window-id",
        summary="小阈值压缩：真发 compact_applied、留可恢复锚、带窗口身份",
        prompt="read both then answer",
        turns=("read:tc1:a.txt", "read:tc2:b.txt", "answer:all done"),
        compaction="tiny",
        expect_types=("compact_started", "compact_applied", "run_completed"),
        expect_window_id=True,
    ),
    EvalTask(
        id="duplicate-command-is-idempotent",
        summary="同一幂等键重写同一条记忆：store 返回原 receipt、不重复 append（写不双份）",
        prompt=FACT_LAUNCH,
        turns=("answer:noted",),
        post=("write_memory", "duplicate_store_write"),
        expect_types=("memory_written",),
        expect_written_count=1,
        expect_idempotent_write=True,
    ),
    EvalTask(
        id="oversized-tool-output-archived",
        summary="超预算工具输出：全文进 artifact，prompt/事件只留有界 preview（C-1）",
        prompt="read the big file",
        turns=("read:tc1:big.txt", "answer:summarised"),
        expect_types=("tool_started", "tool_completed", "run_completed"),
        expect_archived=True,
    ),
)


TASK_BY_ID: dict[str, EvalTask] = {task.id: task for task in TASKS}


@dataclass(frozen=True, slots=True)
class TaskEvidence:
    """一次任务跑完后的全部可判据材料（判分器只看这里，不看模型口气）。"""

    task_id: str
    status: str
    types: tuple[str, ...]
    events: tuple[dict[str, Any], ...] = ()
    memory_text: str = ""
    written_ids: tuple[str, ...] = ()
    deleted_count: int = 0
    cited_ids: tuple[str, ...] = ()
    open_tool_use_ids: tuple[str, ...] = ()
    orphan_result_ids: tuple[str, ...] = ()
    recovery_pointers: int = 0
    window_ids: tuple[str, ...] = ()
    archived: bool = False
    preview_bytes: int = 0
    tokens: int = 0
    written_seq_count: int = 0
    second_write_idempotent: bool | None = None
    source_lines_after_duplicate: int = 0


@dataclass(slots=True)
class GradeOutcome:
    """判分结果：通过位 + 失败原因（不静默：报告里要能看出**哪一条**判据红）。"""

    passed: bool
    failures: list[str] = field(default_factory=list)


def _ordered_subsequence(needle: tuple[str, ...], haystack: tuple[str, ...]) -> bool:
    """`needle` 是否为 `haystack` 的子序列（形状判据：允许中间有别的事件，但顺序不能反）。"""
    cursor = 0
    for item in needle:
        while cursor < len(haystack) and haystack[cursor] != item:
            cursor += 1
        if cursor >= len(haystack):
            return False
        cursor += 1
    return True


def grade(task: EvalTask, evidence: TaskEvidence) -> GradeOutcome:
    """确定性判分器：把任务声明的每条期望逐个核对，返回全部失败项（不是第一个）。"""
    failures: list[str] = []
    if evidence.status != {"run_completed": "COMPLETED", "run_cancelled": "CANCELLED", "run_failed": "FAILED"}[task.terminal]:
        failures.append(f"terminal: expected {task.terminal}, got {evidence.status}")
    if not _ordered_subsequence(task.expect_types, evidence.types):
        failures.append(f"trace shape {task.expect_types} not a subsequence of {evidence.types}")
    for forbidden in task.forbidden_types:
        if forbidden in evidence.types:
            failures.append(f"forbidden event present: {forbidden}")
    if task.must_close_pairs and evidence.open_tool_use_ids:
        failures.append(f"open tool_use after run: {evidence.open_tool_use_ids}")
    if task.must_close_pairs and evidence.orphan_result_ids:
        failures.append(f"head-orphan tool_result after run: {evidence.orphan_result_ids}")
    if task.expect_citations and not evidence.cited_ids:
        failures.append("no citations parsed from message_completed")
    if task.compaction and evidence.recovery_pointers == 0:
        failures.append("compaction configured but no recovery anchor left")
    if task.expect_window_id and not evidence.window_ids:
        failures.append("compact_applied carries no window_id")
    if task.expect_archived and not evidence.archived:
        failures.append(f"oversized output not archived (preview={evidence.preview_bytes}B)")
    if task.expect_written_count is not None and evidence.written_seq_count != task.expect_written_count:
        failures.append(f"memory_written count {evidence.written_seq_count} != {task.expect_written_count}")
    if task.expect_idempotent_write and evidence.second_write_idempotent is not True:
        failures.append(f"re-issued idempotency key did not return the original receipt: {evidence.second_write_idempotent}")
    for fact in task.expected_facts:
        if fact not in evidence.memory_text:
            failures.append(f"expected fact missing from memory store: {fact}")
    return GradeOutcome(passed=not failures, failures=failures)


__all__ = ["FACT_LAUNCH", "FACT_VENDOR", "EvalTask", "GradeOutcome", "TASKS", "TASK_BY_ID", "TaskEvidence", "grade"]
