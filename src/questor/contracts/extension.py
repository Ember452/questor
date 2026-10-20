"""L0 扩展面词表：13 个生效点位 + 4 个预留名 + 6 字段声明（B5；v3 §5.1/§5.2）。

本模块只放**声明期形状**与**纯运行时语义**，不含注册表/工厂/生命周期：

- ``ExtensionDescriptor`` 只有 6 个字段（id/kind/at/matcher/version/priority）。
  刻意没有 ``failure_semantics``：不可回退点位的 fail-closed 是点位内建常量，
  不可被声明覆盖（§20 C-2）。
- ``at`` 是封闭集：13 个生效点位可注册；4 个预留名只能出现在文档/测试里，
  启用需 ADR（本模块不提供注册入口）。
- ``ObserveChain`` 只执行 OBSERVE 条目：条目异常或返回 ``FAILED_ABORT`` 一律
  归一为 ``FAILED_CONTINUE``——观察者不能断链，更不能把 turn 变成失败。
- kernel 只 import 本模块（contracts），不 import ``policy.registry``；链由
  surface/composition 装配后以纯 callable 注入。

依赖方向：只依赖标准库与 :mod:`questor.contracts.common`（L0 最内层）。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from questor.contracts.common import freeze, require_non_empty


# --------------------------------------------------------------------------- #
# 三形状 + 运行期三值
# --------------------------------------------------------------------------- #
class ExtensionKind(StrEnum):
    """扩展的形状（§5.2）：transform/decision 可改 payload，observe 只读。"""

    TRANSFORM = "transform"
    DECISION = "decision"
    OBSERVE = "observe"


class HookOutcomeKind(StrEnum):
    """运行期三值（T7，codex HookResult）：声明期不预置失败策略。"""

    SUCCESS = "success"  # 继续且采用本条结果
    FAILED_CONTINUE = "failed_continue"  # 本条失败，链继续
    FAILED_ABORT = "failed_abort"  # 本条失败，断链并归一失败（仅非 OBSERVE 点位允许）


# --------------------------------------------------------------------------- #
# 封闭点位：13 生效 + 4 预留（上限 17，§21 G3）
# --------------------------------------------------------------------------- #
class InterceptionPoint(StrEnum):
    """13 个**生效**具名点位（§5.1）。名字一旦发布永不改名。"""

    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    PRE_TOOL_USE = "PreToolUse"
    PERMISSION_REQUEST = "PermissionRequest"
    POST_TOOL_USE = "PostToolUse"
    POST_TOOL_USE_FAILURE = "PostToolUseFailure"
    PRE_COMPACT = "PreCompact"
    POST_COMPACT = "PostCompact"
    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    SUBAGENT_START = "SubagentStart"
    SUBAGENT_STOP = "SubagentStop"
    INTERRUPT = "Interrupt"
    STOP = "Stop"


#: 13 个生效点位（有序，供 inspect/守卫稳定输出）。
LIVE_POINTS: tuple[str, ...] = tuple(point.value for point in InterceptionPoint)

#: 4 个预留名：名字先定死，启用需 ADR；``ExtensionDescriptor`` 不接受它们。
RESERVED_POINTS: tuple[str, ...] = ("Notification", "Elicitation", "TaskUpdated", "PlanStep")

#: 全部合法名字（含预留）；上限 = 17（G3）。
ALL_POINTS: frozenset[str] = frozenset((*LIVE_POINTS, *RESERVED_POINTS))

#: 点位 → matcher 的封闭键名（None = 该点不接受 matcher，声明了也忽略并出声）。
_MATCHER_KEY_BY_POINT: dict[str, str | None] = {
    InterceptionPoint.USER_PROMPT_SUBMIT.value: None,
    InterceptionPoint.PRE_TOOL_USE.value: "tool_name",
    InterceptionPoint.PERMISSION_REQUEST.value: "tool_name",
    InterceptionPoint.POST_TOOL_USE.value: "tool_name",
    InterceptionPoint.POST_TOOL_USE_FAILURE.value: "tool_name",
    InterceptionPoint.PRE_COMPACT.value: "trigger",
    InterceptionPoint.POST_COMPACT.value: "trigger",
    InterceptionPoint.SESSION_START.value: "source",
    InterceptionPoint.SESSION_END.value: "reason",
    InterceptionPoint.SUBAGENT_START.value: "agent_type",
    InterceptionPoint.SUBAGENT_STOP.value: "agent_type",
    InterceptionPoint.INTERRUPT.value: None,
    InterceptionPoint.STOP.value: None,
}

#: matcher 的封闭键名集（值必须是字符串；空串拒绝）。
MATCHER_KEYS: frozenset[str] = frozenset({"tool_name", "agent_type", "trigger", "source", "reason"})


def matcher_key_for(at: str) -> str | None:
    """该点位唯一有意义的 matcher 键；None = 不接受 matcher（声明了忽略并出声）。"""
    return _MATCHER_KEY_BY_POINT.get(at)


def matcher_matches(descriptor: ExtensionDescriptor, context: Mapping[str, str]) -> bool:
    """纯匹配：descriptor.matcher 的每个键值都必须等于 context 中同键；无 matcher 恒真。"""
    if descriptor.matcher is None:
        return True
    return all(context.get(str(key)) == str(value) for key, value in descriptor.matcher.items())


# --------------------------------------------------------------------------- #
# 6 字段声明
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class ExtensionDescriptor:
    """声明期形状：是什么、挂哪、对谁生效、多先后（§5.2）。

    ``matcher`` 只对带键点位有意义；本结构不做“按点位裁剪”，因为声明期应允许
    静态可查的完整形状，装配期由 registry 按 ``matcher_key_for`` 校验/告警。
    """

    id: str
    kind: ExtensionKind
    at: str
    matcher: Mapping[str, str] | None = None
    version: int = 1
    priority: int = 100

    def __post_init__(self) -> None:
        require_non_empty(self.id, "ExtensionDescriptor.id")
        if self.at not in LIVE_POINTS:
            if self.at in RESERVED_POINTS:
                raise ValueError(
                    f"extension point {self.at!r} is reserved; enabling it requires an ADR (13 live + 4 reserved)"
                )
            raise ValueError(f"unknown extension point {self.at!r}; live points are {LIVE_POINTS}")
        if self.version <= 0:
            raise ValueError("ExtensionDescriptor.version must be positive")
        if self.matcher is not None:
            if not isinstance(self.matcher, Mapping):
                raise TypeError("ExtensionDescriptor.matcher must be a mapping or None")
            unknown = set(self.matcher) - MATCHER_KEYS
            if unknown:
                raise ValueError(f"unknown matcher key(s) {sorted(unknown)}; allowed: {sorted(MATCHER_KEYS)}")
            for key, value in self.matcher.items():
                require_non_empty(str(value), f"ExtensionDescriptor.matcher[{key!r}]")
            object.__setattr__(self, "matcher", freeze(dict(self.matcher)))

    def fingerprint(self) -> str:
        """内容指纹（inspect/A-B 用；canonical JSON，禁用 repr）。"""
        payload = {
            "id": self.id,
            "kind": self.kind.value,
            "at": self.at,
            "matcher": dict(self.matcher) if self.matcher is not None else None,
            "version": self.version,
            "priority": self.priority,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# 运行期结果 + OBSERVE 链
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class HookOutcome:
    """一次钩子执行的结果；OBSERVE 链会把 FAILED_ABORT 归一为 FAILED_CONTINUE。"""

    kind: HookOutcomeKind = HookOutcomeKind.SUCCESS
    value: Any | None = None
    reason: str | None = None
    entry_id: str | None = None


#: 只读观察钩子：拿 payload（只读快照），不返回改写后的数据。
ObserveHook = Callable[[object], Awaitable[HookOutcome | None]]


@dataclass(frozen=True, slots=True)
class ObserveEntry:
    """注册侧的观察条目：descriptor + 异步钩子（无 init/teardown）。"""

    descriptor: ExtensionDescriptor
    hook: ObserveHook = field(compare=False, hash=False)

    def __post_init__(self) -> None:
        if self.descriptor.kind is not ExtensionKind.OBSERVE:
            raise ValueError("ObserveEntry requires ExtensionDescriptor.kind=OBSERVE")


class ObserveChain:
    """按 priority 降序执行 OBSERVE 条目；任何条目都**不能**断链或改数据。"""

    def __init__(self, entries: tuple[ObserveEntry, ...] = ()) -> None:
        self._entries = tuple(sorted(entries, key=lambda item: (-item.descriptor.priority, item.descriptor.id)))

    def __bool__(self) -> bool:
        return bool(self._entries)

    @property
    def entries(self) -> tuple[ObserveEntry, ...]:
        return self._entries

    async def emit(self, payload: object) -> tuple[HookOutcome, ...]:
        """依次执行；异常与 FAILED_ABORT 均归一为 FAILED_CONTINUE（绝不阻塞 turn）。"""
        outcomes: list[HookOutcome] = []
        for entry in self._entries:
            try:
                outcome = await entry.hook(payload)
            except Exception as exc:  # noqa: BLE001 - 观察者故障只留痕，不阻塞回复
                outcome = HookOutcome(
                    kind=HookOutcomeKind.FAILED_CONTINUE,
                    reason=f"{type(exc).__name__}: {exc}",
                    entry_id=entry.descriptor.id,
                )
            if outcome is None:
                outcome = HookOutcome(entry_id=entry.descriptor.id)
            if outcome.kind is HookOutcomeKind.FAILED_ABORT:
                outcome = HookOutcome(
                    kind=HookOutcomeKind.FAILED_CONTINUE,
                    value=outcome.value,
                    reason=outcome.reason or "observe entries cannot abort the chain",
                    entry_id=entry.descriptor.id,
                )
            outcomes.append(outcome)
        return tuple(outcomes)

    def render(self) -> str:
        """稳定可断言的装配链（inspect-extensions 用）。"""
        lines = [f"{point}" for point in LIVE_POINTS]
        if not self._entries:
            lines.append("  (no observe entries)")
            return "\n".join(lines)
        for entry in self._entries:
            descriptor = entry.descriptor
            lines.append(f"  {descriptor.at}: {descriptor.id} priority={descriptor.priority} v{descriptor.version}")
        return "\n".join(lines)


__all__ = [
    "ALL_POINTS",
    "ExtensionDescriptor",
    "ExtensionKind",
    "HookOutcome",
    "HookOutcomeKind",
    "InterceptionPoint",
    "LIVE_POINTS",
    "MATCHER_KEYS",
    "ObserveChain",
    "ObserveEntry",
    "ObserveHook",
    "RESERVED_POINTS",
    "matcher_key_for",
    "matcher_matches",
]
