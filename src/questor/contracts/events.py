"""L0 Command / Event 词汇表（design/02；HARD C5/C6/C13）。

这些形状编码的铁律：
- 只有 :class:`Command` 改状态；:class:`Event` 是投影，绝不可反哺为状态输入（C5）。
- Command 可校验、可拒绝、非 append-only；Event append-only、发出即不可撤回（C5）。
- 内部事件 ≠ 外部投影；消费者遇未知 ``type`` 静默忽略——错误类事件除外（C6）。

P0 锁定名称 + 信封 + 关联键（永不改名）；``data`` 具体字段留 ``draft``（C11）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

from questor.contracts.common import JsonObject, freeze, require_aware, require_non_empty, utc_now
from questor.contracts.errors import ErrorEntry
from questor.contracts.memory import MemoryCitation, MemoryWrite, RecoveryPointer
from questor.contracts.state_schema import CancelReason, Message, TaskNode

#: 关联键——一旦发布永不改名/删除（design/02 §1）。
CORRELATION_KEYS: frozenset[str] = frozenset(
    {"run_id", "turn", "tool_call_id", "card_id", "item_id"}
)

#: wire 契约版本；仅在破坏性变更时 bump（design/02 §6）。
EVENT_SCHEMA_VERSION = 1


# --------------------------------------------------------------------------- #
# Command（输入事件）——唯一写入口，全部经 reduce。
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class SubmitMessage:
    """用户发起一轮：受理时即占用 durable seq（02 §10）。

    ``flags`` 是**提交方自报的有界标记**（B8 三门控的可跳过一位，如 ``{"skip_recall": true}``
    ——系统/自动轮次不做召回）；它不改正文、不参与安全判定，未知 key 一律忽略（开放词表，
    与 §20 C-6 的 source 口径一致）。additive：默认 ``None`` = 与旧行为逐字等价。
    """

    run_id: str
    content: Message
    flags: JsonObject | None = None
    type: ClassVar[str] = "submit_message"

    def __post_init__(self) -> None:
        if self.flags is not None:
            object.__setattr__(self, "flags", freeze(self.flags))


@dataclass(frozen=True, slots=True)
class RequestApproval:
    """把一次工具调用转为 durable HITL request。

    `request_id` 是超时/取消/人工回执的共同身份；没有它就无法区分同一 tool_call 的多个请求。
    """

    run_id: str
    tool_call_id: str
    request_id: str
    args_summary: str
    risk: str
    reason: str
    expires_at: datetime
    type: ClassVar[str] = "request_approval"

    def __post_init__(self) -> None:
        require_aware(self.expires_at, "RequestApproval.expires_at")


@dataclass(frozen=True, slots=True)
class ResolveApproval:
    """人工审批回执：幂等——同一 request 同决策为 no-op，异决策被拒绝（02 E3/ADR-0016）。"""

    run_id: str
    request_id: str
    decision: str  # allow | deny
    decided_by: str  # user | http_client | cli | system
    type: ClassVar[str] = "resolve_approval"


@dataclass(frozen=True, slots=True)
class ExpireApproval:
    """把唯一 pending request 置 expired；迟到 ResolveApproval 不得翻案。"""

    run_id: str
    request_id: str
    type: ClassVar[str] = "expire_approval"


@dataclass(frozen=True, slots=True)
class MarkToolValidated:
    """记录“已通过 schema/arg-key 校验，可进入权限判定”的账本状态。"""

    run_id: str
    tool_call_id: str
    type: ClassVar[str] = "mark_tool_validated"


@dataclass(frozen=True, slots=True)
class MarkToolRunning:
    """工具从 ready/pending 转为 running，是 `tool_started` 的唯一产生入口。"""

    run_id: str
    tool_call_id: str
    capability: str
    risk: str
    timeout_s: float
    type: ClassVar[str] = "mark_tool_running"


@dataclass(frozen=True, slots=True)
class SetPermissionMode:
    """变更未来调用的权限模式；历史 decision 不回溯（design/01 I5）。"""

    run_id: str
    mode: str  # default | plan | full_auto
    changed_by: str
    type: ClassVar[str] = "set_permission_mode"


@dataclass(frozen=True, slots=True)
class Cancel:
    """取消：经 reduce、不硬杀；置 cancelled 并回填所有未闭合 tool_call（C7）。"""

    run_id: str
    reason: CancelReason
    type: ClassVar[str] = "cancel"


@dataclass(frozen=True, slots=True)
class WriteMemory:
    """记忆写入的唯一途径：经 Command→reduce→StorePort（C4）。

    ADR-0024：载荷从旧的裸 ``JsonObject`` 收敛为 typed :class:`MemoryWrite`，使有界/幂等/权限
    判定可在 reduce 内强制；命令名 ``write_memory`` 与 Command 联合不变（不破信封）。"""

    run_id: str
    payload: MemoryWrite
    type: ClassVar[str] = "write_memory"


@dataclass(frozen=True, slots=True)
class DeleteMemory:
    """记忆撤回的唯一途径：同样经 Command→reduce→消费点（C4/C16）。

    ``entry_id`` 是条目级指针 ``path:start-end``（与 citation/消费打点同粒度），不是数据库主键；
    reduce 只产一条 durable ``memory_deleted`` 事件 + **软删位**，**不建历史表**（§20 C-7）：
    “这条被改过几次”只能从事件流投影。真源 md 文件**不就地删文**（事实流与快照仍是真相）。
    """

    run_id: str
    entry_id: str
    reason: str | None = None
    type: ClassVar[str] = "delete_memory"

    def __post_init__(self) -> None:
        require_non_empty(self.entry_id, "DeleteMemory.entry_id")
        if len(self.entry_id) > 288:
            raise ValueError("DeleteMemory.entry_id exceeds 288 chars")


@dataclass(frozen=True, slots=True)
class RecordWarning:
    """内核需在 ``reduce`` 之外落一条 durable 告警时的唯一入口（保 seq 单调，C2）。

    典型：C10 策略故障回滚前的告警。不产任何状态变更，只占一个 durable seq 并产一条
    ``warning`` 事件——历史实现直接经总线发 ``warning`` 却复用已占 seq，撞 ``event_log``
    UNIQUE 而崩循环（track5-backbone BLK-1 path A）。
    """

    run_id: str
    turn: int | None
    message: str
    type: ClassVar[str] = "record_warning"


@dataclass(frozen=True, slots=True)
class RecordTurnCompleted:
    """内核在 Stop 点落一条 durable ``turn_completed``（B6；与 ``settle_turn`` 同批启用）。

    ``usage`` 只放 base 用量字段（有界对象），``interrupted`` 由 Interrupt 点给出；
    本命令不改变 context/status，只占一个 durable seq 并产出可回放的成本/中断事实。
    """

    run_id: str
    turn: int
    usage: JsonObject | None = None
    interrupted: bool = False
    type: ClassVar[str] = "record_turn_completed"


@dataclass(frozen=True, slots=True)
class CompactContext:
    """P10/ADR-0048：内核在 turn 边界安全点发出的**压缩应用**命令（design/01 I2；HARD C2/C16）。

    关键铁律（对抗评审 MAJ-8）：``summary_text``、``new_pointers``（含 ``covered_hash``）、
    ``new_floor`` 均由 **loop 侧**（可插拔摘要策略，非 provider-in-reduce）算好后随命令携带；
    ``reduce`` **只做纯校验 + 纯应用**，绝不在此计算摘要/哈希——否则 ``pre_compact`` 快照尾重放
    含本命令时重跑摘要器会破回放确定性（design/01 I4）。``evict_start/evict_end`` 为
    ``context.items`` 上待逐出的**连续中段**索引；reduce 要求 ``evict_end <= closed_prefix(items)``
    （C19：绝不孤儿化未闭合 ``tool_use``）。"""

    run_id: str
    evict_start: int
    evict_end: int
    summary_text: str
    new_floor: int
    new_pointers: tuple[RecoveryPointer, ...] = ()
    type: ClassVar[str] = "compact_context"

    def __post_init__(self) -> None:
        if self.evict_start < 0 or self.evict_end < self.evict_start:
            raise ValueError("CompactContext requires 0 <= evict_start <= evict_end")


# ---- 内核内部 Command（仍是 Command，仍经 reduce 单写；C2）----
@dataclass(frozen=True, slots=True)
class AppendAssistantMessage:
    """定稿一条 assistant 消息；其 tool_use 块会在账本登记为 pending 调用。

    ``citations`` 是 harness 从正文里解析出来的**条目级引用**（B8；§6.3）：它随命令进入、
    由 reduce 挂到 ``message_completed`` 事件字段，**不回写进 context 正文**（解析即剥）。
    默认 ``None`` = 旧行为逐字等价。
    """

    run_id: str
    turn: int
    message: Message
    citations: MemoryCitation | None = None
    type: ClassVar[str] = "append_assistant_message"


@dataclass(frozen=True, slots=True)
class AdvanceTurn:
    """推进到下一 turn 号（护栏计数、续跑判定依赖它）。"""

    run_id: str
    turn: int
    type: ClassVar[str] = "advance_turn"


@dataclass(frozen=True, slots=True)
class RecordToolResult:
    """回填工具结果，闭合一个仍打开的调用；只能闭合 pending/running 的（配对不变式）。"""

    run_id: str
    tool_call_id: str
    status: str  # success | error | critical_error | timed_out | cancelled
    result: Any | None = None
    display: Any | None = None
    type: ClassVar[str] = "record_tool_result"


@dataclass(frozen=True, slots=True)
class MarkToolDenied:
    """权限 deny：置 denied 并写 tool_result（denied 也入账、不计失败重试）。"""

    run_id: str
    tool_call_id: str
    reason: str
    type: ClassVar[str] = "mark_tool_denied"


@dataclass(frozen=True, slots=True)
class FinalizeRun:
    """收尾为唯一终态（completed/failed）；终态后 Run 冻结（C13）。"""

    run_id: str
    status: str  # completed | failed
    final: Message | None = None
    usage: JsonObject | None = None
    exit_reason: str | None = None  # turn_exit_reason，用于对外归因（R01 G-1）
    error: ErrorEntry | None = None
    type: ClassVar[str] = "finalize_run"


# ---- P8 子 agent / DAG Command（均经 reduce 单写；ADR-0038）----
@dataclass(frozen=True, slots=True)
class SpawnSubagent:
    """父 run 记账一个子 agent（独立 Run）：绑定 ``assigned_run_id`` + 置 node active + 发 ``peer_started``。

    reduce 是纯状态机、**不创建子 run**（IO 在 loop 消费点经注入端口完成，ADR-0038/§4.1）。
    ``spawn_key`` 是幂等 claim 键（``(parent,node,attempt)``）：重投同键 = no-op，崩溃重启不留孤儿子（v1=at-least-once）。"""

    run_id: str  # 父 run
    node_id: str
    child_run_id: str
    spawn_key: str
    type: ClassVar[str] = "spawn_subagent"

    def __post_init__(self) -> None:
        if not self.spawn_key:
            raise ValueError("SpawnSubagent.spawn_key is required (idempotency claim key)")
        if not self.child_run_id or not self.node_id:
            raise ValueError("SpawnSubagent requires node_id and child_run_id")


@dataclass(frozen=True, slots=True)
class ReportChildTerminal:
    """子 run 终态回灌父 run（经父 inbox，非跨 run 直写）：回填 node + 发 ``peer_ended``。

    ``result_ref`` 是 artifact 指针（非正文，C18/C20/ADR-0019）；父 cancelled 时本命令得 REJECTED_TERMINAL（不复活）。"""

    run_id: str  # 父 run（接收方）
    child_run_id: str
    node_id: str
    terminal_status: str  # completed | failed | cancelled
    result_ref: str | None = None
    resumable_hint: bool = False
    type: ClassVar[str] = "report_child_terminal"

    def __post_init__(self) -> None:
        if self.terminal_status not in {"completed", "failed", "cancelled"}:
            raise ValueError("ReportChildTerminal.terminal_status must be completed, failed or cancelled")


@dataclass(frozen=True, slots=True)
class UpdateTaskTree:
    """承接策略 ``ProposePlanUpdate`` 意图：**首次让 reduce 处理 task_tree**。

    写入前对 ``upsert``+现有节点集跑 DAG 依赖校验（无环/悬空/自环/唯一，ADR-0037）；非法则拒 + 发错误事件、不改树。"""

    run_id: str
    upsert: tuple[TaskNode, ...] = ()
    remove_ids: tuple[str, ...] = ()
    type: ClassVar[str] = "update_task_tree"


Command = (
    SubmitMessage
    | RequestApproval
    | ResolveApproval
    | ExpireApproval
    | SetPermissionMode
    | MarkToolValidated
    | MarkToolRunning
    | Cancel
    | WriteMemory
    | DeleteMemory
    | CompactContext
    | AppendAssistantMessage
    | AdvanceTurn
    | RecordToolResult
    | MarkToolDenied
    | FinalizeRun
    | SpawnSubagent
    | ReportChildTerminal
    | UpdateTaskTree
    | RecordWarning
    | RecordTurnCompleted
)


# --------------------------------------------------------------------------- #
# Event（输出）——信封 + 外部投影的类型名。
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Envelope:
    """事件信封：``{v, seq, run_id, turn?, ts, type, data}``。data 深冻结（C2）。"""

    v: int
    seq: int
    run_id: str
    type: str
    ts: datetime = field(default_factory=utc_now)
    turn: int | None = None
    data: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.seq < 0:
            raise ValueError("Envelope.seq must be >= 0")
        object.__setattr__(self, "data", freeze(self.data))


class EventType:
    """对外事件的 ``type`` 取值域（design/02 §3）。只增不改（C6）。"""

    RUN_STARTED = "run_started"
    TURN_STARTED = "turn_started"
    TEXT_DELTA = "text_delta"  # 仅实时、永不持久化（I3）
    REASONING_DELTA = "reasoning_delta"  # live-only
    MESSAGE_COMPLETED = "message_completed"
    TOOL_STARTED = "tool_started"
    TOOL_PROGRESS = "tool_progress"  # live-only
    TOOL_COMPLETED = "tool_completed"
    APPROVAL_REQUEST = "approval_request"
    APPROVAL_RESOLVED = "approval_resolved"
    PERMISSION_MODE_CHANGED = "permission_mode_changed"
    NODE_UPDATED = "node_updated"
    USAGE_DELTA = "usage_delta"
    HEARTBEAT = "heartbeat"  # live-only
    RUN_CANCELLED = "run_cancelled"  # 先于 run_completed
    RUN_FAILED = "run_failed"
    RUN_COMPLETED = "run_completed"
    RESYNC_REQUIRED = "resync_required"
    WARNING = "warning"  # 非终态告警（02 §10）
    MEMORY_WRITTEN = "memory_written"  # 记忆写入回执（有界、无原文；ADR-0024/0026）
    PEER_STARTED = "peer_started"  # 父 spawn 子 agent（P8；ADR-0042）
    PEER_ENDED = "peer_ended"  # 子 agent 达终态回父（P8；ADR-0042）
    TOOLS_CHANGED = "tools_changed"  # 能力名册变更 live-only 告警（P9；ADR-0046，design/02 §7）
    COMPACT_STARTED = "compact_started"  # 压缩开始（P10；ADR-0048，design/02 §10）
    COMPACT_APPLIED = "compact_applied"  # 压缩应用 + baseline_seq 栅栏（P10；ADR-0048，design/02 §10）
    # 用户原话 durable（B1；设计文档 §4.2 事实流补齐）：非 idle 提交把有界正文写进事实流，
    # 使「重放 = 生产」与 --resume 的可见转录不依赖第二真相（idle 首条仍由 run_started + 快照承载，
    # 既有冻结断言 test_reduce.py:51 / test_transition_chokepoint.py:45 不改）。
    USER_MESSAGE = "user_message"
    # turn 边界（B6；设计文档 §5.1 的 Stop 点）：durable 成本/中断事实，供 settle_turn 与
    # 桌面“这轮花了多少”消费；只带 usage/interrupted，无正文（C18/C20）。
    TURN_COMPLETED = "turn_completed"
    # 记忆索引段已注入本轮请求（B7；设计文档 §6.1 四道约束的第④条）：live-only 观测条目，
    # 只带条目 id 与有界计量（行数/字节数），**无索引正文**——“注入了什么”可审计，“内容是什么”
    # 永不进日志/wire（C18/C20）。
    MEMORY_INJECTED = "memory_injected"
    # prompt cache 断裂（B7；设计文档 §6.1 cache 三条款之第 3 条）：live-only，只带三段 hash
    # （system 块 / 工具面 / 历史起点）+ 断裂原因位 + 断点数，零明文（C18/C20）。
    CACHE_BREAK = "cache_break"
    # 记忆被**消费**（B8；设计文档 §6.3 硬规定）：live-only。kind = 层级（memory_md/index/raw/summary/skills），
    # entry_id = 条目级 `path:start-end`。命不等于消费：`memory_search` 命中不发本事件，
    # 只有真读了（Read/memory_read）或被 citation 引用才算；不可识别的工具直接不计数（宁缺不猜）。
    MEMORY_CONSUMED = "memory_consumed"
    # 记忆撤回（B9；§6.4-6 / §20 C-7）：durable，与 `is_deleted` 软删位同步产生。
    # 只带条目 id 与短原因，无正文；**不开 `memory_history` 表**，回放时从事件流重建撤回史。
    MEMORY_DELETED = "memory_deleted"


#: 未知时不得被静默丢弃的事件类型（C6 的例外：错误类至少告警）。
ERROR_CLASS_EVENT_TYPES: frozenset[str] = frozenset(
    {EventType.RUN_FAILED, EventType.WARNING, EventType.RESYNC_REQUIRED}
)


__all__ = [
    "CORRELATION_KEYS",
    "EVENT_SCHEMA_VERSION",
    "SubmitMessage",
    "ResolveApproval",
    "Cancel",
    "WriteMemory",
    "DeleteMemory",
    "CompactContext",
    "AppendAssistantMessage",
    "AdvanceTurn",
    "RecordToolResult",
    "MarkToolDenied",
    "FinalizeRun",
    "Command",
    "Envelope",
    "EventType",
    "ERROR_CLASS_EVENT_TYPES",
    "SpawnSubagent",
    "ReportChildTerminal",
    "UpdateTaskTree",
    "RecordWarning",
    "RecordTurnCompleted",
]
