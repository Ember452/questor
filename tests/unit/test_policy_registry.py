"""P9 T3：进程内 PolicyRegistry（ADR-0045）——注册/解析/trust 优先级/错误二分/fail-open/AB 分桶。

真依赖判据：不是"字段存在≠gate 存在"——本测钉 resolve 真按 trust 选、破损真留名、
fail-open 真回落默认并 WARN、AB 真按 split_key 确定性分桶（同键同策略、多键分布）。
"""

from __future__ import annotations

import logging

import pytest

from questor.policy.registry import (
    BrokenPolicyError,
    PolicyEntry,
    PolicyRegistry,
    UnknownPolicyError,
    ab_select,
)


class _FakePolicy:
    """最小 PolicyPort 替身：registry 只调 factory() 得实例、读 .id/.fingerprint。"""

    def __init__(self, pid: str, fp: str) -> None:
        self.id = pid
        self.fingerprint = fp

    def propose_action(self, view):  # pragma: no cover - 不在本测调用
        raise NotImplementedError


def _entry(pid: str, fp: str, trust, broken: str | None = None) -> PolicyEntry:
    factory: object
    if broken is not None:
        factory = None
    else:
        factory = lambda pid=pid, fp=fp: _FakePolicy(pid, fp)  # noqa: E731
    return PolicyEntry(id=pid, factory=factory, trust=trust, broken_reason=broken)


def test_resolve_returns_registered_policy() -> None:
    from questor.contracts.policy import PolicyTrust

    reg = PolicyRegistry(default_id="react")
    reg.register(_entry("react", "react:1", PolicyTrust.SYSTEM))
    port = reg.resolve("react")
    assert port.id == "react" and port.fingerprint == "react:1"


def test_unknown_policy_error_lists_known_roster() -> None:
    from questor.contracts.policy import PolicyTrust

    reg = PolicyRegistry(default_id="react")
    reg.register(_entry("react", "react:1", PolicyTrust.SYSTEM))
    with pytest.raises(UnknownPolicyError) as exc:
        reg.resolve("ghost")
    assert "react" in str(exc.value)  # 附名册


def test_broken_policy_keeps_name_and_raises_broken() -> None:
    from questor.contracts.policy import PolicyTrust

    reg = PolicyRegistry(default_id="react")
    reg.register(_entry("react", "react:1", PolicyTrust.SYSTEM))
    reg.register(_entry("corrupt", "", PolicyTrust.PROJECT, broken="import exploded"))
    with pytest.raises(BrokenPolicyError) as exc:
        reg.resolve("corrupt")
    assert "import exploded" in str(exc.value)
    assert "corrupt" in reg.known()  # 破损留名、不静默消失


def test_trust_priority_project_beats_system() -> None:
    from questor.contracts.policy import PolicyTrust

    reg = PolicyRegistry(default_id="react")
    reg.register(_entry("react", "system-copy", PolicyTrust.SYSTEM))
    reg.register(_entry("react", "project-copy", PolicyTrust.PROJECT))
    port = reg.resolve("react")
    assert port.fingerprint == "project-copy"  # project 覆盖 system（design/05 §2）


def test_fail_open_returns_default_and_warns(caplog) -> None:
    from questor.contracts.policy import PolicyTrust

    reg = PolicyRegistry(default_id="react")
    reg.register(_entry("react", "react:1", PolicyTrust.SYSTEM))
    with caplog.at_level(logging.WARNING, logger="questor.policy.registry"):
        port, ref = reg.resolve_or_default("does-not-exist")
    assert port.id == "react"  # 绝不让 run 起不来（C10）
    assert ref.id == "react" and ref.fingerprint == "react:1"
    assert any("does-not-exist" in r.message or "fallback" in r.message.lower() for r in caplog.records)


def test_ab_bucket_is_deterministic_and_distributes() -> None:
    weights = {"a": 1, "b": 1}
    # 同 split_key → 同桶（确定性）。
    first = ab_select("run-42", weights)
    assert ab_select("run-42", weights) == first
    assert first in {"a", "b"}
    # 多键应覆盖两桶（概率上必然，但取足够样本钉"能分流"）。
    seen = {ab_select(f"run-{i}", weights) for i in range(200)}
    assert seen == {"a", "b"}


def test_ab_single_variant_always_that_variant() -> None:
    # n=1 安全默认：只一个候选则恒选它（不分流）。
    assert {ab_select(f"k{i}", {"react": 1}) for i in range(50)} == {"react"}
