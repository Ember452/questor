"""L0 状态词汇表：被 state(L1) 与 policy(L4) 共享的值对象 + 枚举。

之所以放在最内层 contracts：内外层都要 import 它们而不成环（STRUCTURE §2）。这里只有
**形状 + 局部不变式**；跨对象不变式与唯一写者 ``reduce`` 在 :mod:`questor.state`
（design/01 §12 I1）。字段细节在 P1 前保持 ``draft``（C11）——P0 锁定的是接缝名与
关联键。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from questor.contracts.common import JsonObject, freeze, require_aware, utc_now


class RunStatus(StrEnum):
    """一次 Run 的生命周期状态；终态唯一（C13）。"""

    IDLE = "idle"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    CANCELLED = "cancelled"
    FAILED = "failed"
    COMPLETED = "completed"

    @property
    def is_terminal(self) -> bool:
        """是否为终态：终态后 Run 冻结，任何后续 Command 一律被拒（first-writer-wins）。"""
        return self in {RunStatus.CANCELLED, RunStatus.FAILED, RunStatus.COMPLETED}


class CancelReason(StrEnum):
    """统一的取消归因枚举，对齐 design/02 §5 / 04 §2 / HARD C7（修正 R01 D8 的三处漂移）。"""

    USER = "user"
    TIMEOUT = "timeout"
    BUDGET_EXHAUSTED = "budget_exhausted"
    NO_PROGRESS = "no_progress"
    SAFETY = "safety"
    OWNER = "owner"


class Role(StrEnum):
    """消息作者角色；映射到 provider 消息语义。"""

    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


class ToolCallStatus(StrEnum):
    """工具调用账本状态；denied 也入账（审计），且不计入失败重试（design/01 §6）。

    P2 生命周期要求每个 transition 都由带类型 Command 驱动；`validated/awaiting_approval/ready` 是
    审批与取消可恢复的中间态，不能被简化成 loop 内存变量。
    """

    PENDING = "pending"
    VALIDATED = "validated"
    AWAITING_APPROVAL = "awaiting_approval"
    READY = "ready"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    CRITICAL_ERROR = "critical_error"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    DENIED = "denied"


class ToolArgsStatus(StrEnum):
    """provider 工具入参的可解析状态。

    非法 JSON 绝不能伪装成空对象继续跑；这里把“参数事实”与 schema 校验解耦（ADR-0016）。
    """

    VALID = "valid"
    INVALID = "invalid"
    MISSING = "missing"


class ApprovalStatus(StrEnum):
    """一次审批请求的状态；每个 request 有独立身份，迟到决策不能翻案。"""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


#: 表示「调用仍未闭合（无结果）」的状态集合——配对不变式、取消回填(C7)、策略的
#: 「未应答 tool_use」判定都复用它，避免各处口径漂移。
OPEN_TOOL_CALL_STATUSES: frozenset[ToolCallStatus] = frozenset(
    {
        ToolCallStatus.PENDING,
        ToolCallStatus.VALIDATED,
        ToolCallStatus.AWAITING_APPROVAL,
        ToolCallStatus.READY,
        ToolCallStatus.RUNNING,
    }
)

#: 终态工具结果；这些状态不再允许被普通 RecordToolResult 重复闭合。
CLOSED_TOOL_CALL_STATUSES: frozenset[ToolCallStatus] = frozenset(
    {
        ToolCallStatus.SUCCESS,
        ToolCallStatus.ERROR,
        ToolCallStatus.CRITICAL_ERROR,
        ToolCallStatus.TIMED_OUT,
        ToolCallStatus.CANCELLED,
        ToolCallStatus.DENIED,
    }
)


class TaskStatus(StrEnum):
    """任务树节点状态。"""

    PENDING = "pending"
    ACTIVE = "active"
    BLOCKED = "blocked"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    # 多 agent 汇聚预留态（design/01 §13）；v1 不使用。
    WAITING_CHILDREN = "waiting_children"


class TaskKind(StrEnum):
    """节点类型；subagent 为 P8 占位。"""

    TASK = "task"
    SUBAGENT = "subagent"  # 占位直到 P8（design/01 §3）


@dataclass(frozen=True, slots=True)
class ContentBlock:
    """消息中的一段内容：text | reasoning | tool_use | tool_result | image | file。

    由 ``type`` 决定哪些可选字段有意义。P0 用单一形状以「只增不改」演进（image/file
    复用 ``payload`` 承载）。"""

    type: str  # "text" | "reasoning" | "tool_use" | "tool_result" | "image" | "file"
    text: str | None = None
    tool_use_id: str | None = None  # tool_use 与 tool_result 的配对关联键
    name: str | None = None  # 工具名（tool_use）
    input: JsonObject | None = None  # 工具入参（tool_use）
    is_error: bool | None = None  # tool_result 的错误标志
    payload: dict[str, Any] | None = None  # image/file 的不透明载体
    provider_state: dict[str, Any] | None = None  # 不透明、reducer 只搬运不解释（R03 A-2）
    raw_input: str | None = None  # provider 原始 args；非法 JSON 不得伪装成空参
    args_status: ToolArgsStatus = ToolArgsStatus.MISSING
    args_error: str | None = None  # 仅可解析性错误摘要，不保存未截断原文

    def __post_init__(self) -> None:
        # 深冻结 dict 叶，确保被 COW 共享的实例无法被就地篡改（HARD C2）。
        object.__setattr__(self, "input", freeze(self.input) if self.input is not None else None)
        object.__setattr__(self, "payload", freeze(self.payload) if self.payload is not None else None)
        object.__setattr__(
            self, "provider_state", freeze(self.provider_state) if self.provider_state is not None else None
        )
        if self.args_status is ToolArgsStatus.VALID and self.input is None:
            raise ValueError("valid ContentBlock.input must be a JSON object")
        if self.args_status is ToolArgsStatus.INVALID and not self.raw_input:
            raise ValueError("invalid tool args must retain a bounded raw_input summary")


@dataclass(frozen=True, slots=True)
class Message:
    """一条消息（定稿块）。瞬态 delta 不在此列——delta 只走事件流、永不入状态(I3)。"""

    id: str
    role: Role
    content: tuple[ContentBlock, ...]
    seq: int
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.seq < 0:
            raise ValueError("Message.seq must be >= 0")
        require_aware(self.created_at, "Message.created_at")


@dataclass(frozen=True, slots=True)
class TaskNode:
    """任务树节点（森林）。计划进状态而非接口（design/01 §3）。"""

    id: str
    title: str
    objective: str = ""
    parent_id: str | None = None  # 森林：顶层节点 parent 为空
    kind: TaskKind = TaskKind.TASK
    status: TaskStatus = TaskStatus.PENDING
    deps: tuple[str, ...] = ()  # v1 仅做前置读校验，不做拓扑调度（design/01 I6）
    assigned_run_id: str | None = None
    result: str | None = None


@dataclass(frozen=True, slots=True)
class ToolCall:
    """工具调用账本条目：可审计、可重放、与事件按 ``tool_call_id`` 关联。"""

    tool_call_id: str
    turn: int
    name: str
    args: JsonObject
    status: ToolCallStatus = ToolCallStatus.PENDING
    result: Any | None = None  # 给模型的返回
    display: Any | None = None  # 给人的展示（卡片）
    permission_decision: str | None = None
    args_status: ToolArgsStatus = ToolArgsStatus.MISSING
    raw_args_summary: str | None = None
    approval_request_id: str | None = None
    permission_reason: str | None = None
    permission_decided_by: str | None = None
    permission_warnings: tuple[str, ...] = ()
    capability: str | None = None
    risk: str | None = None
    timeout_s: float | None = None
    sandbox_backend: str | None = None
    confinement: str | None = None
    env_scrubbed: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    node_id: str | None = None
    seq_request: int | None = None  # 发起时占用的 durable seq
    seq_result: int | None = None  # 返回时占用的 durable seq
    started_at: datetime | None = None
    ended_at: datetime | None = None

    def __post_init__(self) -> None:
        # args 深冻结：账本条目会跨 COW 共享（HARD C2）。
        object.__setattr__(self, "args", freeze(self.args))


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    """一次 HITL 审批请求的持久身份（ADR-0016）。

    `request_id` 是幂等边界：同一 request 的重复决策不产新事件；过期后迟到决策不得翻案。
    `args_summary` 必须是已脱敏/截断摘要，工具原始参数不得直接外发。
    """

    request_id: str
    tool_call_id: str
    args_summary: str
    risk: str
    reason: str
    created_at: datetime
    expires_at: datetime
    status: ApprovalStatus = ApprovalStatus.PENDING
    decision: str | None = None
    decided_by: str | None = None
    resolved_at: datetime | None = None

    def __post_init__(self) -> None:
        # 时间必须可比较且带时区；否则 timeout/replay/checkpoint 会跨机器漂出错误结论。
        require_aware(self.created_at, "ApprovalRequest.created_at")
        require_aware(self.expires_at, "ApprovalRequest.expires_at")
        if self.expires_at < self.created_at:
            raise ValueError("ApprovalRequest.expires_at must not be before created_at")
        if self.resolved_at is not None:
            require_aware(self.resolved_at, "ApprovalRequest.resolved_at")
        if self.status is not ApprovalStatus.PENDING and (self.decision is None or self.resolved_at is None):
            raise ValueError("resolved ApprovalRequest requires decision and resolved_at")


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """run 的可恢复快照点（design/01 §5）。"""

    cp_id: str
    seq: int
    turn: int
    kind: str  # auto | manual | pre_tool | post_tool | pre_compact
    state_digest: str  # 指向该点状态（P1 存整份快照的序列化）
    # 中断时未闭合的 tool_use，供恢复时回填/修复（design/01 §5）。
    pending_tool_calls: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PermissionRule:
    """二维通配权限规则：permission(工具名) × pattern(参数串) → action。"""

    pattern: str
    action: str  # allow | ask | deny
    scope: str = "*"


@dataclass(frozen=True, slots=True)
class Budget:
    """一次 run 的预算与护栏阈值（护栏阈值全部配置化、绝不硬编码，design/04 L4）。

    P1 由 turn loop 强制：``max_turns``、``deadline_seconds``（墙钟）、``max_tokens``
    （用量）、``repeat_tool_limit``（同工具同参连续）、``max_consecutive_continuations``
    （连续空答）。"""

    max_turns: int = 25
    max_tokens: int | None = None
    deadline_seconds: float | None = None
    repeat_tool_limit: int = 3
    max_consecutive_continuations: int = 8
    approval_timeout_seconds: float = 300
    tool_default_timeout_seconds: float = 120

    def __post_init__(self) -> None:
        # 审批/工具超时是 fail-closed 默认；非法值必须在状态构造期拒绝。
        if self.approval_timeout_seconds <= 0:
            raise ValueError("Budget.approval_timeout_seconds must be positive")
        if self.tool_default_timeout_seconds <= 0:
            raise ValueError("Budget.tool_default_timeout_seconds must be positive")
