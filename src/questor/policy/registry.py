"""L4 进程内扩展/策略注册表（design/05 §2/§3；ADR-0045；B5 §5.2）。

两层职责，共用同一套 trust 与 A/B 语义：

- :class:`ExtensionRegistry`：B5 的通用声明式注册表——存 ``ExtensionDescriptor`` + 工厂，
  按 ``at`` 分组、按 priority 降序解析；治理字段（``trust``/``broken_reason``）留在注册侧，
  **不进**声明结构。
- :class:`PolicyRegistry`：既有策略名册的兼容外壳，保留 ``_pick_entry``/``resolve_or_default``/
  ``ab_select`` 全部语义；内部改存 ``ExtensionEntry``，因此 ``inspect-extensions`` 能同时
  看到策略与观察者。

**边界（C1）**：只 import ``contracts``；kernel(L2)/surfaces(L6) 都不 import 本模块——
解析发生在组合根/surface，解析得 callable/PolicyPort 再注入 loop。发现边界钉死为
**进程内注册固定名册**，无磁盘扫描/HMR（防过度工程，AGENTS §2/C12）。
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from questor.contracts.extension import (
    LIVE_POINTS,
    RESERVED_POINTS,
    ExtensionDescriptor,
    ExtensionKind,
    InterceptionPoint,
    ObserveChain,
    ObserveEntry,
    matcher_matches,
)
from questor.contracts.policy import PolicyPort, PolicyRef, PolicyTrust

_log = logging.getLogger("questor.policy.registry")

#: trust 优先级秩：project > user > system（design/05 §2）。
_TRUST_RANK: dict[PolicyTrust, int] = {
    PolicyTrust.SYSTEM: 0,
    PolicyTrust.USER: 1,
    PolicyTrust.PROJECT: 2,
}


class UnknownPolicyError(Exception):
    """策略 id 未注册（写错名）；附当前名册——区别于"存在但破损"（design/05 §2）。"""

    def __init__(self, policy_id: str, known: set[str]) -> None:
        super().__init__(f"unknown policy {policy_id!r}; known policies: {sorted(known)}")
        self.policy_id = policy_id
        self.known = frozenset(known)


class BrokenPolicyError(Exception):
    """策略已注册但加载/部署/构造错（附 reason）；**破损留名、不静默消失**（design/05 §2）。"""

    def __init__(self, policy_id: str, reason: str) -> None:
        super().__init__(f"broken policy {policy_id!r}: {reason}")
        self.policy_id = policy_id
        self.reason = reason


class _PolicyFactory(Protocol):
    def __call__(self) -> PolicyPort: ...


@dataclass(frozen=True, slots=True)
class PolicyEntry:
    """策略注册条目：``{id, factory, trust, broken?, descriptor?}``（design/05 §2）。

    ``broken_reason`` 非空或 ``factory is None`` 表示这是一个"已知但破损"的策略——
    保留在名册里（供诊断/fail-open 出声），解析时抛 :class:`BrokenPolicyError`。
    ``descriptor`` 是 B5 的声明期形状；缺省时按 ``UserPromptSubmit`` 变换条目合成，
    使旧调用方一行不改。
    """

    id: str
    factory: _PolicyFactory | None
    trust: PolicyTrust = PolicyTrust.SYSTEM
    broken_reason: str | None = None
    descriptor: ExtensionDescriptor | None = None


@dataclass(frozen=True, slots=True)
class ExtensionEntry:
    """通用注册条目：descriptor（声明）+ factory（运行期解析）+ 治理位（注册侧）。"""

    descriptor: ExtensionDescriptor
    factory: Callable[[], object] | None
    trust: PolicyTrust = PolicyTrust.SYSTEM
    broken_reason: str | None = None


def ab_select(split_key: str, weights: dict[str, int]) -> str:
    """A/B 分桶：按 ``split_key`` **确定性**地在加权候选里选一个 policy id（ADR-0045 决策 8）。

    用 sha256 而非内置 ``hash()``——后者按进程 PYTHONHASHSEED 加盐、跨进程不稳定，会破坏
    "同键同策略"的回归可比性。单候选（n=1）恒返该候选=不分流的安全默认。"""
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("ab_select requires positive total weight")
    bucket = int(hashlib.sha256(split_key.encode("utf-8")).hexdigest(), 16) % total
    acc = 0
    last = ""
    # 稳定遍历顺序（按 id 排序），使分桶不依赖 dict 插入顺序。
    for pid in sorted(weights):
        acc += weights[pid]
        last = pid
        if bucket < acc:
            return pid
    return last  # 防御：整除边界，理论不达


def _pick_entry(entries: list[ExtensionEntry]) -> ExtensionEntry:
    """trust 最高者胜；同级后注册（最近根）覆盖——用 (rank, 注册序) 取 max。"""
    return max(enumerate(entries), key=lambda it: (_TRUST_RANK[it[1].trust], it[0]))[1]


class ExtensionRegistry:
    """通用声明式注册表：按 ``at`` 解析观察链/打印装配链（不持有运行期实例）。"""

    def __init__(self) -> None:
        self._entries: dict[str, list[ExtensionEntry]] = defaultdict(list)

    def register(self, entry: ExtensionEntry) -> None:
        """登记一个扩展条目；同名重复不覆盖，按 trust + 注册次序在解析时择一。"""
        self._entries[entry.descriptor.id].append(entry)

    def known(self) -> set[str]:
        """当前名册（含破损项——留名）。"""
        return set(self._entries)

    def all_entries(self) -> tuple[ExtensionEntry, ...]:
        """全部条目（inspect/守卫用；顺序按注册 id 稳定排序）。"""
        return tuple(entry for entry_id in sorted(self._entries) for entry in self._entries[entry_id])

    def entries_for(self, at: str, *, matcher: Mapping[str, str] | None = None) -> tuple[ExtensionEntry, ...]:
        """某点位的条目，按 priority 降序、id 升序；matcher 给定时只留匹配项。"""
        selected = [entry for entry in self.all_entries() if entry.descriptor.at == at]
        if matcher is not None:
            selected = [entry for entry in selected if matcher_matches(entry.descriptor, matcher)]
        return tuple(sorted(selected, key=lambda entry: (-entry.descriptor.priority, entry.descriptor.id)))

    def resolve(self, entry_id: str) -> object:
        """解析一个条目为工厂产物；破损/工厂抛错一律 :class:`BrokenPolicyError`（留名出声）。"""
        entries = self._entries.get(entry_id)
        if not entries:
            raise UnknownPolicyError(entry_id, self.known())
        chosen = _pick_entry(entries)
        if chosen.broken_reason is not None or chosen.factory is None:
            raise BrokenPolicyError(entry_id, chosen.broken_reason or "no factory (broken placeholder)")
        try:
            return chosen.factory()
        except Exception as exc:  # noqa: BLE001 - 构造错=Broken，留名出声（CancelledError 属 BaseException 不被捕）
            raise BrokenPolicyError(entry_id, f"factory raised {type(exc).__name__}: {exc}") from exc

    def resolve_observe(self, at: str, *, matcher: Mapping[str, str] | None = None) -> ObserveChain:
        """把某点位的 OBSERVE 条目解析成链；破损条目留名后跳过（观察者自隔离）。"""
        observe_entries: list[ObserveEntry] = []
        for entry in self.entries_for(at, matcher=matcher):
            if entry.descriptor.kind is not ExtensionKind.OBSERVE:
                continue
            if entry.broken_reason is not None or entry.factory is None:
                _log.warning("observe entry %r at %s is broken: %s", entry.descriptor.id, at, entry.broken_reason)
                continue
            try:
                hook = entry.factory()
            except Exception as exc:  # noqa: BLE001 - 单个观察者构造失败不得拖垮整链
                _log.warning("observe entry %r at %s failed to resolve: %s", entry.descriptor.id, at, exc)
                continue
            if not callable(hook):
                _log.warning("observe entry %r at %s resolved to non-callable", entry.descriptor.id, at)
                continue
            observe_entries.append(ObserveEntry(entry.descriptor, hook))
        return ObserveChain(tuple(observe_entries))

    def render_chain(self) -> str:
        """稳定可断言的装配链（inspect-extensions 用）；ASCII-only 便于跨代码页输出。"""
        lines = [f"extension points: {len(LIVE_POINTS)} live + {len(RESERVED_POINTS)} reserved"]
        for at in LIVE_POINTS:
            lines.append(f"[{at}]")
            entries = self.entries_for(at)
            if not entries:
                lines.append("  (none)")
                continue
            for entry in entries:
                descriptor = entry.descriptor
                broken = f" broken={entry.broken_reason}" if entry.broken_reason else ""
                lines.append(
                    f"  {descriptor.id} kind={descriptor.kind.value} priority={descriptor.priority} "
                    f"v{descriptor.version} trust={entry.trust.value}{broken}"
                )
        lines.append(f"reserved (ADR-gated): {', '.join(RESERVED_POINTS)}")
        return "\n".join(lines)


class PolicyRegistry(ExtensionRegistry):
    """进程内策略注册表。构造时给一个 ``default_id`` 作为 fail-open 回落目标（必已注册）。

    兼容外形：``register(PolicyEntry)`` / ``resolve(id)`` / ``resolve_or_default(...)`` 与
    ``known()`` 的语义与旧实现逐字一致；内部存储改为 :class:`ExtensionEntry`，因此策略
    也出现在 ``inspect-extensions`` 的 ``UserPromptSubmit`` 点位下。
    """

    def __init__(self, default_id: str) -> None:
        super().__init__()
        self._default_id = default_id

    def register(self, entry: PolicyEntry) -> None:  # type: ignore[override]
        """登记一个策略条目；同名重复不覆盖、按 trust 优先级 + 注册次序在 resolve 时择一。"""
        descriptor = entry.descriptor or ExtensionDescriptor(
            id=entry.id,
            kind=ExtensionKind.TRANSFORM,
            at=InterceptionPoint.USER_PROMPT_SUBMIT.value,
            priority=100,
        )
        super().register(
            ExtensionEntry(
                descriptor=descriptor,
                factory=entry.factory,
                trust=entry.trust,
                broken_reason=entry.broken_reason,
            )
        )

    def resolve(self, policy_id: str) -> PolicyPort:
        """解析为一个 PolicyPort 实例。

        失败语义：未注册→:class:`UnknownPolicyError`（附名册）；条目破损或工厂抛错→
        :class:`BrokenPolicyError`（留名、附 reason）——均**不静默吞**。"""
        entries = self._entries.get(policy_id)
        if not entries:
            raise UnknownPolicyError(policy_id, self.known())
        chosen = _pick_entry(entries)
        if chosen.broken_reason is not None or chosen.factory is None:
            raise BrokenPolicyError(policy_id, chosen.broken_reason or "no factory (broken placeholder)")
        try:
            return chosen.factory()  # type: ignore[return-value]
        except Exception as exc:  # noqa: BLE001 - 构造错=Broken，留名出声（CancelledError 属 BaseException 不被捕）
            raise BrokenPolicyError(policy_id, f"factory raised {type(exc).__name__}: {exc}") from exc

    def resolve_or_default(
        self,
        policy_id: str,
        *,
        split_key: str = "",
        ab_table: dict[str, int] | None = None,
    ) -> tuple[PolicyPort, PolicyRef]:
        """fail-open 解析（C10，绝不让 run 起不来）：给 (port, PolicyRef) 供装配冻结进 run。

        - 有 ``ab_table`` 时按 ``split_key`` 选变体 id，否则用传入 ``policy_id``。
        - Unknown/Broken → WARN + 回落 ``default_id``（默认策略自身破损则如实上抛，
          因为没有可回落目标、不能假装成功）。"""
        target = ab_select(split_key, ab_table) if ab_table else policy_id
        try:
            port = self.resolve(target)
        except (UnknownPolicyError, BrokenPolicyError) as exc:
            _log.warning(
                "policy %r unavailable (%s); fallback to default %r", target, type(exc).__name__, self._default_id
            )
            port = self.resolve(self._default_id)
        return port, PolicyRef(id=port.id, fingerprint=port.fingerprint)


__all__ = [
    "BrokenPolicyError",
    "ExtensionEntry",
    "ExtensionRegistry",
    "PolicyEntry",
    "PolicyRegistry",
    "UnknownPolicyError",
    "ab_select",
]
