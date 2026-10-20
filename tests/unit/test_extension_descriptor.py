"""B5 T1：ExtensionDescriptor 6 字段 + 13 生效/4 预留封闭名单（v3 §5.1/§5.2；§21 G3）。"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping

import pytest

from questor.contracts.extension import (
    ALL_POINTS,
    LIVE_POINTS,
    MATCHER_KEYS,
    RESERVED_POINTS,
    ExtensionDescriptor,
    ExtensionKind,
    HookOutcome,
    HookOutcomeKind,
    InterceptionPoint,
    ObserveChain,
    ObserveEntry,
    matcher_key_for,
    matcher_matches,
)


def test_descriptor_has_exactly_six_fields() -> None:
    names = [field.name for field in dataclasses.fields(ExtensionDescriptor)]
    assert names == ["id", "kind", "at", "matcher", "version", "priority"]
    assert "failure_semantics" not in names


def test_live_and_reserved_points_are_closed() -> None:
    assert len(LIVE_POINTS) == 13
    assert len(RESERVED_POINTS) == 4
    assert len(ALL_POINTS) == 17
    assert LIVE_POINTS == tuple(point.value for point in InterceptionPoint)
    assert set(RESERVED_POINTS) == {"Notification", "Elicitation", "TaskUpdated", "PlanStep"}


def test_reserved_point_cannot_be_registered_without_adr() -> None:
    with pytest.raises(ValueError, match="reserved"):
        ExtensionDescriptor(id="elicitation", kind=ExtensionKind.DECISION, at="Elicitation")


def test_unknown_point_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown extension point"):
        ExtensionDescriptor(id="bogus", kind=ExtensionKind.OBSERVE, at="NotAPoint")


def test_observe_cannot_declare_fail_closed() -> None:
    # 声明结构没有 failure_semantics；传它必须是 TypeError，而不是被静默接受。
    with pytest.raises(TypeError):
        ExtensionDescriptor(id="x", kind=ExtensionKind.OBSERVE, at="Stop", failure_semantics="fail_closed")  # type: ignore[call-arg]


def test_matcher_is_frozen_and_closed_key_set() -> None:
    descriptor = ExtensionDescriptor(
        id="no-write-tools", kind=ExtensionKind.DECISION, at="PreToolUse", matcher={"tool_name": "write"}
    )
    assert isinstance(descriptor.matcher, Mapping)
    with pytest.raises(TypeError):
        descriptor.matcher["tool_name"] = "bash"  # type: ignore[index]
    with pytest.raises(ValueError, match="unknown matcher key"):
        ExtensionDescriptor(id="x", kind=ExtensionKind.DECISION, at="PreToolUse", matcher={"path": "/tmp"})
    with pytest.raises(ValueError, match="must not be empty"):
        ExtensionDescriptor(id="x", kind=ExtensionKind.DECISION, at="PreToolUse", matcher={"tool_name": ""})


def test_matcher_key_is_per_point() -> None:
    assert matcher_key_for("PreToolUse") == "tool_name"
    assert matcher_key_for("SessionStart") == "source"
    assert matcher_key_for("Stop") is None
    assert MATCHER_KEYS == {"tool_name", "agent_type", "trigger", "source", "reason"}


def test_matcher_matches_requires_every_declared_key() -> None:
    descriptor = ExtensionDescriptor(
        id="read-only-session", kind=ExtensionKind.OBSERVE, at="SessionStart", matcher={"source": "cli"}
    )
    assert matcher_matches(descriptor, {"source": "cli"})
    assert not matcher_matches(descriptor, {"source": "http"})
    assert not matcher_matches(descriptor, {})
    plain = ExtensionDescriptor(id="plain", kind=ExtensionKind.OBSERVE, at="Stop")
    assert matcher_matches(plain, {})


async def test_observe_chain_runs_by_priority_and_never_aborts() -> None:
    seen: list[str] = []

    async def make(name: str, outcome: HookOutcome | None = None, *, boom: bool = False):  # noqa: ANN202
        async def hook(_payload: object) -> HookOutcome | None:
            seen.append(name)
            if boom:
                raise RuntimeError("observer exploded")
            return outcome

        return hook

    low = ExtensionDescriptor(id="low", kind=ExtensionKind.OBSERVE, at="Stop", priority=10)
    high = ExtensionDescriptor(id="high", kind=ExtensionKind.OBSERVE, at="Stop", priority=200)
    abort = ExtensionDescriptor(id="abort", kind=ExtensionKind.OBSERVE, at="Stop", priority=50)
    chain = ObserveChain(
        (
            ObserveEntry(low, await make("low")),
            ObserveEntry(high, await make("high", HookOutcome(kind=HookOutcomeKind.FAILED_ABORT, reason="no"))),
            ObserveEntry(abort, await make("abort", boom=True)),
        )
    )
    outcomes = await chain.emit(object())
    assert seen == ["high", "abort", "low"]  # priority 降序
    assert [o.kind for o in outcomes] == [
        HookOutcomeKind.FAILED_CONTINUE,
        HookOutcomeKind.FAILED_CONTINUE,
        HookOutcomeKind.SUCCESS,
    ]
    # OBSERVE 的 FAILED_ABORT 被归一，且异常被兜住；链从未抛出。
    assert all(o.kind is not HookOutcomeKind.FAILED_ABORT for o in outcomes)


def test_observe_entry_requires_observe_kind() -> None:
    async def hook(_payload: object) -> HookOutcome:  # pragma: no cover - 不会执行
        return HookOutcome()

    with pytest.raises(ValueError, match="kind=OBSERVE"):
        ObserveEntry(ExtensionDescriptor(id="x", kind=ExtensionKind.DECISION, at="Stop"), hook)


def test_fingerprint_is_canonical_not_repr() -> None:
    one = ExtensionDescriptor(id="a", kind=ExtensionKind.OBSERVE, at="Stop", priority=1)
    two = ExtensionDescriptor(id="a", kind=ExtensionKind.OBSERVE, at="Stop", priority=1)
    assert one.fingerprint() == two.fingerprint()
    assert len(one.fingerprint()) == 16
