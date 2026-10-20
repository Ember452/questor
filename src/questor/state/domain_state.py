"""L1 Domain_State 聚合（design/01）。P0 只有形状 + 构造不变式，无 reduce。

Harness 全程唯一可信状态：权威、可序列化、可回放、可断点。本模块把 L0 词汇组合成
``Run`` / ``DomainState``，并在**构造期**强制局部不变式。
跨对象不变式（``tool_use``↔``tool_result`` 配对、DAG 无环）与唯一写者 ``reduce`` 在
:mod:`questor.state.reduce`（P1，design/01 §12 I1）。

不可变纪律（C2）：集合字段一律 ``tuple``/``frozenset``——frozen dataclass 配不可变
容器才是真深只读，浅冻结会漏改内层。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from questor.contracts.common import JsonObject, freeze, require_aware, utc_now
from questor.contracts.errors import ErrorEntry
from questor.contracts.memory import RecoveryPointer
from questor.contracts.policy import PolicyRef
from questor.contracts.state_schema import (
    ApprovalRequest,
    Budget,
    CancelReason,
    Checkpoint,
    Message,
    PermissionRule,
    RunStatus,
    TaskNode,
    ToolCall,
)


@dataclass(frozen=True, slots=True)
class Context:
    """会话上下文 + 压缩边界（design/01 §2）。"""

    items: tuple[Message, ...] = ()
    compaction_floor: int | None = None  # 已压缩区下界
    summary: str | None = None  # 对已压区的摘要
    recovery_pointers: tuple[RecoveryPointer, ...] = ()  # 指向被压原文区间的 typed 指针 (seq_from, seq_to, covered_hash)；P4 定形 + 读前 fail-closed，其生产者（压缩写锚）随 disable_compaction 后置 P10（ADR-0024）


@dataclass(frozen=True, slots=True)
class TaskTree:
    """任务节点森林（v1 严格森林；DAG 后置，I6）。"""

    nodes: tuple[TaskNode, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolLedger:
    """工具调用账本：可审计、可重放、与事件按 tool_call_id 关联。"""

    calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True, slots=True)
class PermissionDecisionRecord:
    """单条权限决策记录（审计用；mode 变更不回溯已发生的决策，I5）。"""

    tool_call_id: str
    decision: str  # allow | ask | deny
    decided_by: str  # rule | user
    at: datetime = field(default_factory=utc_now)
    request_id: str | None = None


@dataclass(frozen=True, slots=True)
class PermissionCtx:
    """三态权限上下文（design/01 §6；决策/求值在 kernel，这里只存状态）。

    ADR-0014：`mode/rules/denylist/approvals` 都是权威状态，不另在引擎里存一份配置。
    """

    mode: str = "default"  # default | plan | full_auto
    rules: tuple[PermissionRule, ...] = ()
    denylist: frozenset[str] = frozenset()  # 不可被 rules/mode 覆盖的敏感路径
    approvals: tuple[ApprovalRequest, ...] = ()  # 每个 request 有独立幂等身份
    decisions: tuple[PermissionDecisionRecord, ...] = ()
    workspace_root: str | None = None
    cwd: str | None = None
    approval_policy: str = "on_request"  # on_request | never
    protect_sensitive_paths: bool = True
    enforce_read_only: bool = False


@dataclass(frozen=True, slots=True)
class Run:
    """一次执行——断点/回放/续传的单位（design/01 §1）。"""

    run_id: str
    seq: int = 0  # 本 run 单调事件游标（after_seq 续传）
    turn: int = 0
    status: RunStatus = RunStatus.IDLE
    budget: Budget = field(default_factory=Budget)
    context: Context = field(default_factory=Context)
    task_tree: TaskTree = field(default_factory=TaskTree)
    tool_ledger: ToolLedger = field(default_factory=ToolLedger)
    checkpoints: tuple[Checkpoint, ...] = ()
    permission_ctx: PermissionCtx = field(default_factory=PermissionCtx)
    error_stack: tuple[ErrorEntry, ...] = ()
    cancel_reason: CancelReason | None = None
    # P9/ADR-0045 additive：run 创建时经 PolicyRegistry 解析、按值快照冻结；默认 None 不破既有构造点/旧快照。
    policy_ref: PolicyRef | None = None
    #: B13 additive：本 run 是从哪个旧 run 的哪个位点**回退/分叉**而来的指针。
    #: 形状固定 `{"run_id": str, "to_seq": int}`；None = 普通新 run（旧快照读回 None，不猜）。
    history_base: JsonObject | None = None
    created_at: datetime = field(default_factory=utc_now)
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        # 只强制局部、廉价的不变式；序列号不得倒退。
        if self.seq < 0:
            raise ValueError("Run.seq must be >= 0")
        if self.turn < 0:
            raise ValueError("Run.turn must be >= 0")
        require_aware(self.created_at, "Run.created_at")
        if self.history_base is not None:
            # 只校验形状，不猜语义：缺键或 to_seq 为负都是上游 bug，宁拒不误放。
            # 用 Mapping 而不是 dict：freeze() 出来的是 immutables.Map，`replace(run, …)` 再过一次
            # __post_init__ 时必须是幂等的（否则一条回退事实会在下一次任何状态迁移上崩）。
            if not isinstance(self.history_base, Mapping):
                raise ValueError("Run.history_base must be a mapping")
            if not self.history_base.get("run_id") or not isinstance(self.history_base.get("to_seq"), int):
                raise ValueError('Run.history_base requires {"run_id": non-empty str, "to_seq": int}')
            if self.history_base["to_seq"] < 0:
                raise ValueError("Run.history_base.to_seq must be >= 0")
            object.__setattr__(self, "history_base", freeze(self.history_base))  # freeze 对 Map 幂等
        # 终态一致性（C13）：一轮至多一个终态且字段自洽。
        if self.status.is_terminal:
            if self.completed_at is None:
                raise ValueError("terminal Run requires completed_at")
            if self.status is RunStatus.CANCELLED and self.cancel_reason is None:
                raise ValueError("cancelled Run requires cancel_reason")
            if self.status is RunStatus.FAILED and not self.error_stack:
                raise ValueError("failed Run requires a non-empty error_stack")
        else:
            if self.completed_at is not None:
                raise ValueError("non-terminal Run cannot have completed_at")
            if self.cancel_reason is not None:
                raise ValueError("non-terminal Run cannot carry cancel_reason")


@dataclass(frozen=True, slots=True)
class SessionDefaults:
    """会话级默认值（不可变；design/01 §1）。"""

    model: str | None = None
    locale: str = "en"
    permission_mode: str = "default"


@dataclass(frozen=True, slots=True)
class DomainState:
    """会话根：一个用户可见的长期对话线（§1）。"""

    session_id: str
    runs: tuple[Run, ...] = ()
    defaults: SessionDefaults = field(default_factory=SessionDefaults)

    def active_run(self, run_id: str) -> Run | None:
        """只读查找，不改状态（写一律经 reduce）。"""
        return next((r for r in self.runs if r.run_id == run_id), None)


__all__ = [
    "Context",
    "TaskTree",
    "ToolLedger",
    "PermissionDecisionRecord",
    "PermissionCtx",
    "Run",
    "DomainState",
    "SessionDefaults",
]
