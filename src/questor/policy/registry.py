"""L4 进程内 PolicyRegistry（design/05 §2/§3；ADR-0045）。

职责：注册/解析策略 + trust 优先级（project>user>system、最近根覆写重名）+ 错误二分
（Unknown vs Broken，破损**留名不静默消失**）+ **降级 fail-open**（回落默认 + WARN，
绝不让 run 起不来，C10）+ A/B 按内容 ``fingerprint`` 分桶路由。

**边界（C1）**：只 import ``contracts``；kernel(L2)/surfaces(L6) 都不 import 本模块——
策略的解析发生在组合根/surface，解析得 :class:`PolicyPort` 再注入 loop。发现边界钉死为
**进程内注册固定名册**，无磁盘扫描/HMR（防过度工程，AGENTS §2/C12）。工厂产出的
PolicyPort 实例只读视图→出意图，registry 不碰执行/权限/持久化。
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Protocol

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
    """注册条目：``{id, factory, trust, broken?}``（design/05 §2）。

    ``broken_reason`` 非空或 ``factory is None`` 表示这是一个"已知但破损"的策略——
    保留在名册里（供诊断/fail-open 出声），解析时抛 :class:`BrokenPolicyError`。"""

    id: str
    factory: _PolicyFactory | None
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


class PolicyRegistry:
    """进程内策略注册表。构造时给一个 ``default_id`` 作为 fail-open 回落目标（必已注册）。"""

    def __init__(self, default_id: str) -> None:
        self._default_id = default_id
        # id → 同名多条目（不同 trust/来源）；解析按 trust 秩 + 最近注册择一。
        self._entries: dict[str, list[PolicyEntry]] = defaultdict(list)

    def register(self, entry: PolicyEntry) -> None:
        """登记一个策略条目。同名重复不覆盖、按 trust 优先级 + 注册次序在 resolve 时择一。"""
        self._entries[entry.id].append(entry)

    def known(self) -> set[str]:
        """当前名册（含破损项——留名）。"""
        return set(self._entries)

    def _pick(self, entries: list[PolicyEntry]) -> PolicyEntry:
        """trust 最高者胜；同级后注册（最近根）覆盖——用 (rank, 注册序) 取 max。"""
        return max(enumerate(entries), key=lambda it: (_TRUST_RANK[it[1].trust], it[0]))[1]

    def resolve(self, policy_id: str) -> PolicyPort:
        """解析为一个 PolicyPort 实例。

        失败语义：未注册→:class:`UnknownPolicyError`（附名册）；条目破损或工厂抛错→
        :class:`BrokenPolicyError`（留名、附 reason）——均**不静默吞**。"""
        entries = self._entries.get(policy_id)
        if not entries:
            raise UnknownPolicyError(policy_id, self.known())
        chosen = self._pick(entries)
        if chosen.broken_reason is not None or chosen.factory is None:
            raise BrokenPolicyError(policy_id, chosen.broken_reason or "no factory (broken placeholder)")
        try:
            return chosen.factory()
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
    "PolicyEntry",
    "PolicyRegistry",
    "UnknownPolicyError",
    "ab_select",
]
