"""L4 策略契约（design/05）。P0 固定接口形状。

归属边界（05 §0）：策略拥有提示词 / 工具 allowlist / 算法；**不拥有**模型路由、
审批/denylist、沙箱、持久化写。它读 :class:`PolicyView`（只读视图）、返回一个**不可信**
的 :class:`PolicyIntent`，执行/校验/记账全在 Harness。纯数据 → 天然可序列化，但
**v1 不引入任何 RPC/传输**（C12）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import ClassVar, Protocol

from questor.contracts.common import JsonObject
from questor.contracts.memory import MemorySearchResult
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
    memory: tuple[MemorySearchResult, ...] = ()  # 有界检索命中只读投影（design/05 §1；C4：无裸句柄）


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
class CompactionConfig:
    """P10/ADR-0048：内核可恢复压缩的旋钮（取代旧 `disable_compaction` bool）。

    默认 ``None``（LoopPolicy 未配）**= 不压缩**，向后兼容既有行为。开启后由 loop 在 turn
    边界安全点据此判定是否压缩（I2 内核决定、策略只能发 advisory）；阈值取单一真源
    （``trigger_tokens`` 对比累计 token），loop 只消费不重推窗口数学。

    B10/§7.1 口径重写：给了 ``context_window`` 后走 **绝对阈值**（Claude-Code 同族口径，
    推翻 v2 的 fraction），未给则逐字退回旧的 ``trigger_tokens``/``max_items`` 路径（既有测试不
    受影响）。三个阈值都是算出来的、不是拍出来的：

    - 有效窗口 ``EW = context_window − min(max_output, summary_reserve)``；
    - 自动阈值 ``EW − max(summary_reserve, auto_buffer)``（摘要自己也要预留输出，否则摘要溢出）；
    - 手动阈值 ``EW − manual_buffer``（用户主动 `/compact` 用更紧的界）；
    - 预警阈值 ``EW − warning_buffer``（“快满了”可见告警，比自动阈值更早）。

    - ``keep_head``：从头保留不被逐出的条数（保护开头 user/系统轮）；
    - ``keep_tail``：从尾保留的条数（保住最新可见回复与在途区）；
    - ``trigger_tokens``：累计用量达此阈值才触发（None=不因 token 触发）；
    - ``max_items``：context 条数超此值才触发（None=不因条数触发）。
    两者均 None 且未给 ``context_window`` 时不触发（保守默认，与 ADR-0041 一致）。"""

    keep_head: int = 2
    keep_tail: int = 2
    trigger_tokens: int | None = None
    max_items: int | None = None
    # ---- B10/§7.1 绝对阈值面（additive：不给 context_window 就逐字走旧路径）----
    #: 模型的上下文窗口（token）；来自 `providers/model_windows.py`，None = 不知道窗口。
    context_window: int | None = None
    #: 模型的最大输出（token）；参与 ``min(max_output, summary_reserve)`` 计算。
    max_output: int | None = None
    #: 摘要输出预留（20_000，取 Claude-Code `autoCompact.ts` 实测常量；改前需先自测，§17-8）。
    summary_reserve: int = 20_000
    #: 自动压缩缓冲（13_000，同上游 `AUTOCOMPACT_BUFFER_TOKENS`）。
    auto_buffer: int = 13_000
    #: 手动压缩缓冲（3_000，同上游 `MANUAL_COMPACT_BUFFER`）。
    manual_buffer: int = 3_000
    #: 预警缓冲（26_000）：**questor 自定值、无上游实测来源**，ADR-0057 的 p99 实测后才能改。
    warning_buffer: int = 26_000
    #: 可压工具白名单；None = 用 :data:`COMPACTABLE_TOOLS` 默认（写类结果不压）。
    compactable_tools: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if self.keep_head < 0 or self.keep_tail < 0:
            raise ValueError("CompactionConfig.keep_head/keep_tail must be >= 0")
        for name in ("summary_reserve", "auto_buffer", "manual_buffer", "warning_buffer"):
            if getattr(self, name) <= 0:
                raise ValueError(f"CompactionConfig.{name} must be > 0")
        if self.context_window is not None:
            if self.context_window <= 0:
                raise ValueError("CompactionConfig.context_window must be > 0")
            if self.effective_window() is None or self.auto_threshold() is None:
                raise ValueError(
                    "CompactionConfig.context_window is too small to leave any usable window; "
                    "it must exceed both summary_reserve and manual_buffer"
                )

    def effective_window(self) -> int | None:
        """§7.1 有效窗口 = ``context_window − min(max_output, summary_reserve)``。

        未给 ``max_output`` 时按 ``summary_reserve`` 计（即扣满预留）——宁保守也不高估可用空间。"""
        if self.context_window is None:
            return None
        deduct = min(self.max_output, self.summary_reserve) if self.max_output is not None else self.summary_reserve
        usable = self.context_window - deduct
        return usable if usable > 0 else None

    def threshold(self, trigger: str) -> int | None:
        """按触发来路取绝对阈值；未给 ``context_window`` 返回 None（退回旧信号）。

        ``trigger`` 闭集：``auto`` / ``manual`` / ``warning``——与事件里的 `trigger` 字段同源，
        不猜：未知来路直接拒（fail-closed，与配置非法值拒绝启动同口径）。"""
        effective = self.effective_window()
        if effective is None:
            return None
        if trigger == "auto":
            value = effective - max(self.summary_reserve, self.auto_buffer)
        elif trigger == "manual":
            value = effective - self.manual_buffer
        elif trigger == "warning":
            value = effective - self.warning_buffer
        else:
            raise ValueError(f"unknown compaction trigger {trigger!r}; use auto/manual/warning")
        return value if value > 0 else None

    def auto_threshold(self) -> int | None:
        return self.threshold("auto")

    def manual_threshold(self) -> int | None:
        return self.threshold("manual")

    def warning_threshold(self) -> int | None:
        return self.threshold("warning")

    def compactable(self) -> tuple[str, ...]:
        """本配置生效的可压工具白名单（未配则用默认 :data:`COMPACTABLE_TOOLS`）。"""
        return COMPACTABLE_TOOLS if self.compactable_tools is None else tuple(self.compactable_tools)


#: §7.2 白名单：只读检索类与受控 shell 的输出可折叠；**写类工具（write/edit/apply_patch）与
#: 子 agent 报告（delegate）的结果不压**——它们要么就是任务本身，要么不可重建。
COMPACTABLE_TOOLS: tuple[str, ...] = (
    "read",
    "grep",
    "glob",
    "ls",
    "memory_search",
    "bash",
    "powershell",
)


@dataclass(frozen=True, slots=True)
class LoopPolicy:
    """内核侧每次 run 的策略旋钮。"""

    max_turns: int = 25
    disable_tools: bool = False
    # P10/ADR-0048：旧 `disable_compaction: bool` 转正为结构化 ``compaction: CompactionConfig | None``。
    # None = 不压缩（等价于旧的 disable_compaction=True 默认）；配一个 config 才开启可恢复压缩。
    compaction: CompactionConfig | None = None


class PolicyTrust(StrEnum):
    """策略来源信任级（design/05 §2；ADR-0045）。resolve 时 project>user>system、最近根覆写重名。

    形状先行；分桶/优先级消费者在 L4 `PolicyRegistry`（T3）接通，本枚举只定词表。"""

    SYSTEM = "system"
    USER = "user"
    PROJECT = "project"


@dataclass(frozen=True, slots=True)
class PolicyRef:
    """run 内快照冻结的策略标识（ADR-0009/0045）：``id`` + 内容 ``fingerprint``。

    创建 run 时经 :class:`PolicyRegistry` 解析一次、按值冻结进 ``Run.policy_ref``，整 run 用同一份；
    热替换=新 run、AB 按 fingerprint 路由（fingerprint 是内容指纹非版本号，ADR-0009 决策2）。
    `run_started` 事件带此引用（additive、不 bump `v`）。"""

    id: str
    fingerprint: str


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
    "COMPACTABLE_TOOLS",
    "CompactionConfig",
    "LoopPolicy",
    "PolicyTrust",
    "PolicyRef",
    "PolicyPort",
]
