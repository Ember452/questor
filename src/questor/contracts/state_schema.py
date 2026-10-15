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
    """工具调用账本状态；denied 也入账（审计），且不计入失败重试（design/01 §6）。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    CRITICAL_ERROR = "critical_error"
    DENIED = "denied"


#: 表示「调用仍未闭合（无结果）」的状态集合——配对不变式、取消回填(C7)、策略的
#: 「未应答 tool_use」判定都复用它，避免各处口径漂移。
OPEN_TOOL_CALL_STATUSES: frozenset[ToolCallStatus] = frozenset({ToolCallStatus.PENDING, ToolCallStatus.RUNNING})


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

    def __post_init__(self) -> None:
        # 深冻结 dict 叶，确保被 COW 共享的实例无法被就地篡改（HARD C2）。
        object.__setattr__(self, "input", freeze(self.input) if self.input is not None else None)
        object.__setattr__(self, "payload", freeze(self.payload) if self.payload is not None else None)
        object.__setattr__(
            self, "provider_state", freeze(self.provider_state) if self.provider_state is not None else None
        )


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
    node_id: str | None = None
    seq_request: int | None = None  # 发起时占用的 durable seq
    seq_result: int | None = None  # 返回时占用的 durable seq
    started_at: datetime | None = None
    ended_at: datetime | None = None

    def __post_init__(self) -> None:
        # args 深冻结：账本条目会跨 COW 共享（HARD C2）。
        object.__setattr__(self, "args", freeze(self.args))


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
