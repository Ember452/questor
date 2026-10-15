"""L4 策略契约（design/05；R01 G-6 loopdriver）。P0 固定接口形状。

归属边界（05 §0）：策略拥有提示词 / 工具 allowlist / 算法；**不拥有**模型路由、
审批/denylist、沙箱、持久化写。它读 :class:`PolicyView`（只读视图）、返回一个**不可信**
的 :class:`PolicyIntent`，执行/校验/记账全在 Harness。纯数据 → 天然可序列化，但
**v1 不引入任何 RPC/传输**（C12）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Protocol

from questor.contracts.common import JsonObject
from questor.contracts.state_schema import Budget, Message, ToolCall
from questor.contracts.tool import ToolSpec


@dataclass(frozen=True, slots=True)
class PolicyView:
    """策略唯一能读的东西：只读、按字段投影的快照。

    绝不暴露 checkpoints / 权限上下文 / LoopState / 内部元数据（C2/C3）；靠 COW/
    结构共享，不做每轮全量深拷贝。"""

    context: tuple[Message, ...] = ()
    task_tree: tuple[JsonObject, ...] = ()  # 节点投影（字段留 draft）
    tool_results: tuple[ToolCall, ...] = ()
    tools: tuple[ToolSpec, ...] = ()
    budget: Budget = field(default_factory=Budget)


@dataclass(frozen=True, slots=True)
class ProposeToolCall:
    """建议调用某工具；``tool_call_id`` 关联 assistant 消息里那条未应答的 tool_use。"""

    name: str
    args: JsonObject
    tool_call_id: str | None = None  # 由策略回填，内核据此精确闭合对应 pending 调用
    node_id: str | None = None
    type: ClassVar[str] = "propose_tool_call"


@dataclass(frozen=True, slots=True)
class ProposePlanUpdate:
    """建议对任务树的计划变更（多步计划进状态、单步接口出意图）。"""

    ops: tuple[JsonObject, ...]
    type: ClassVar[str] = "propose_plan_update"


@dataclass(frozen=True, slots=True)
class AdviseCompact:
    """仅建议（advisory）：压缩由内核决定（design/01 I2）。"""

    pressure: float
    type: ClassVar[str] = "advise_compact"


@dataclass(frozen=True, slots=True)
class SuggestFinish:
    """建议收尾；是否真的终止由内核判定（C7）。"""

    final_text: str | None = None
    type: ClassVar[str] = "suggest_finish"


@dataclass(frozen=True, slots=True)
class SuggestCancel:
    """建议取消（如策略自检到死循环）；全局终止权在内核。"""

    reason: str
    type: ClassVar[str] = "suggest_cancel"


#: 策略输出=不可信输入；内核行动前先校验（design/04 L1）。
PolicyIntent = ProposeToolCall | ProposePlanUpdate | AdviseCompact | SuggestFinish | SuggestCancel


@dataclass(frozen=True, slots=True)
class LoopPolicy:
    """内核侧每次 run 的策略旋钮（wuu loopdriver 形状，R01 G-6）。"""

    max_turns: int = 25
    disable_tools: bool = False
    disable_compaction: bool = True  # 压缩到 P10 才启用


class PolicyPort(Protocol):
    """可插拔的 Agent 策略。策略里绝不出现 execute/沙箱/StorePort 写句柄。

    P1 的进程内策略（如 ReAct）显式继承本协议以做具名类型。``id``/``fingerprint``
    是策略级数据：run 内快照冻结、AB 按 fingerprint 路由（ADR-0009）。"""

    id: str
    fingerprint: str

    def init(self) -> None: ...

    def propose_action(self, view: PolicyView) -> PolicyIntent: ...

    def on_tool_result(self, result: ToolCall) -> None: ...

    def dispose(self) -> None: ...


__all__ = [
    "PolicyView",
    "ProposeToolCall",
    "ProposePlanUpdate",
    "AdviseCompact",
    "SuggestFinish",
    "SuggestCancel",
    "PolicyIntent",
    "LoopPolicy",
    "PolicyPort",
]
