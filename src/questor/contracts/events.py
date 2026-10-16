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

from questor.contracts.common import JsonObject, freeze, require_aware, utc_now
from questor.contracts.errors import ErrorEntry
from questor.contracts.state_schema import CancelReason, Checkpoint, Message, TaskNode

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
    """用户发起一轮：受理时即占用 durable seq（02 §10）。"""

    run_id: str
    content: Message
    type: ClassVar[str] = "submit_message"


@dataclass(frozen=True, slots=True)
class ProposeAction:
    """承载策略单步意图的 Command。"""

    run_id: str
    turn: int
    # 来自 PolicyPort 的单步意图（design/05）；属不可信输入，内核执行前先校验。
    intent: JsonObject
    type: ClassVar[str] = "propose_action"


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
    """记忆写入的唯一途径：经 Command→reduce→StorePort（C4）。"""

    run_id: str
    payload: JsonObject
    type: ClassVar[str] = "write_memory"


@dataclass(frozen=True, slots=True)
class RequestCompactHint:
    """仅建议压缩压力，不强制；何时/如何压缩由内核决定（design/01 I2）。"""

    run_id: str
    pressure: float
    type: ClassVar[str] = "request_compact_hint"


# ---- 内核内部 Command（仍是 Command，仍经 reduce 单写；C2）----
@dataclass(frozen=True, slots=True)
class AppendAssistantMessage:
    """定稿一条 assistant 消息；其 tool_use 块会在账本登记为 pending 调用。"""

    run_id: str
    turn: int
    message: Message
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


Command = (
    SubmitMessage
    | ProposeAction
    | RequestApproval
    | ResolveApproval
    | ExpireApproval
    | SetPermissionMode
    | MarkToolValidated
    | MarkToolRunning
    | Cancel
    | WriteMemory
    | RequestCompactHint
    | AppendAssistantMessage
    | AdvanceTurn
    | RecordToolResult
    | MarkToolDenied
    | FinalizeRun
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


#: 未知时不得被静默丢弃的事件类型（C6 的例外：错误类至少告警）。
ERROR_CLASS_EVENT_TYPES: frozenset[str] = frozenset(
    {EventType.RUN_FAILED, EventType.WARNING, EventType.RESYNC_REQUIRED}
)


@dataclass(frozen=True, slots=True)
class RunFailedData:
    """``run_failed`` 的 data：携归一化错误（含 retryable/resumable）。"""

    error: ErrorEntry
    type: ClassVar[str] = EventType.RUN_FAILED


@dataclass(frozen=True, slots=True)
class RunCompletedData:
    """``run_completed`` 的 data：最终答复 + 用量 + 退出归因。"""

    final: Message | None = None
    usage: JsonObject | None = None
    exit_reason: str | None = None  # turn_exit_reason（R01 G-1）
    type: ClassVar[str] = EventType.RUN_COMPLETED


@dataclass(frozen=True, slots=True)
class TextDeltaData:
    """``text_delta`` 的 data：一段可见文本增量（live-only）。"""

    delta: str
    item_id: str | None = None
    type: ClassVar[str] = EventType.TEXT_DELTA


# 内部领域事件（私有、可随实现演进；投影为外部后才外发）。P0 只留最小集，
# 完整内部集在 P1 随 turn 循环补齐（design/02 §2/§8）。
@dataclass(frozen=True, slots=True)
class NodeUpdated:
    """任务树节点状态变更（内部）。"""

    node: TaskNode
    type: ClassVar[str] = EventType.NODE_UPDATED


@dataclass(frozen=True, slots=True)
class CheckpointRecorded:
    """落了一个 checkpoint（内部，不进对外投影）。"""

    checkpoint: Checkpoint
    type: ClassVar[str] = "checkpoint_recorded"


__all__ = [
    "CORRELATION_KEYS",
    "EVENT_SCHEMA_VERSION",
    "SubmitMessage",
    "ProposeAction",
    "ResolveApproval",
    "Cancel",
    "WriteMemory",
    "RequestCompactHint",
    "AppendAssistantMessage",
    "AdvanceTurn",
    "RecordToolResult",
    "MarkToolDenied",
    "FinalizeRun",
    "Command",
    "Envelope",
    "EventType",
    "ERROR_CLASS_EVENT_TYPES",
    "RunFailedData",
    "RunCompletedData",
    "TextDeltaData",
    "NodeUpdated",
    "CheckpointRecorded",
]
