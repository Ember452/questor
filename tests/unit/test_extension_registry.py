"""B5 T2：ExtensionRegistry 泛化（保留 PolicyRegistry/ab_select 全部语义；v3 §5.2）。"""

from __future__ import annotations

from questor.contracts.extension import ExtensionDescriptor, ExtensionKind, HookOutcome
from questor.contracts.policy import PolicyTrust
from questor.policy.registry import (
    ExtensionEntry,
    ExtensionRegistry,
    PolicyEntry,
    PolicyRegistry,
    ab_select,
)


class _FakePolicy:
    def __init__(self, pid: str, fp: str) -> None:
        self.id = pid
        self.fingerprint = fp


def _descriptor(entry_id: str, *, priority: int = 100, at: str = "Stop", matcher: dict | None = None) -> ExtensionDescriptor:
    return ExtensionDescriptor(id=entry_id, kind=ExtensionKind.OBSERVE, at=at, matcher=matcher, priority=priority)


async def test_entries_for_is_priority_desc_and_matcher_aware() -> None:
    registry = ExtensionRegistry()

    async def hook(_payload: object) -> HookOutcome:
        return HookOutcome()

    registry.register(ExtensionEntry(_descriptor("low", priority=10), lambda: hook))
    registry.register(ExtensionEntry(_descriptor("high", priority=50), lambda: hook))
    registry.register(
        ExtensionEntry(_descriptor("write-only", at="PostToolUse", matcher={"tool_name": "write"}), lambda: hook)
    )
    assert [entry.descriptor.id for entry in registry.entries_for("Stop")] == ["high", "low"]
    assert [entry.descriptor.id for entry in registry.entries_for("PostToolUse", matcher={"tool_name": "write"})] == [
        "write-only"
    ]
    assert registry.entries_for("PostToolUse", matcher={"tool_name": "read"}) == ()


async def test_resolve_observe_skips_non_observe_and_broken_entries() -> None:
    registry = ExtensionRegistry()

    async def hook(_payload: object) -> HookOutcome:
        return HookOutcome()

    decision = ExtensionDescriptor(id="decide", kind=ExtensionKind.DECISION, at="Stop")
    registry.register(ExtensionEntry(decision, lambda: hook))
    registry.register(ExtensionEntry(_descriptor("broken"), None, broken_reason="factory exploded"))
    registry.register(ExtensionEntry(_descriptor("good"), lambda: hook))
    chain = registry.resolve_observe("Stop")
    assert [entry.descriptor.id for entry in chain.entries] == ["good"]


def test_render_chain_lists_13_live_and_4_reserved() -> None:
    registry = ExtensionRegistry()
    text = registry.render_chain()
    assert "13 live + 4 reserved" in text
    assert "[Stop]" in text
    assert "Notification, Elicitation, TaskUpdated, PlanStep" in text


def test_policy_registry_still_resolves_by_trust_and_lists_at_prompt_submit() -> None:
    registry = PolicyRegistry(default_id="react")
    registry.register(PolicyEntry(id="react", factory=lambda: _FakePolicy("react", "system:1"), trust=PolicyTrust.SYSTEM))
    registry.register(PolicyEntry(id="react", factory=lambda: _FakePolicy("react", "project:1"), trust=PolicyTrust.PROJECT))
    port = registry.resolve("react")
    assert port.fingerprint == "project:1"
    assert {entry.descriptor.id for entry in registry.entries_for("UserPromptSubmit")} == {"react"}
    # 同名策略仍保留两条治理变体，由 trust 择一（first-class 行为不变）。
    assert len(registry.entries_for("UserPromptSubmit")) == 2


def test_ab_select_is_unchanged() -> None:
    assert ab_select("same-key", {"a": 1}) == "a"
    assert ab_select("same-key", {"a": 1, "b": 1}) == ab_select("same-key", {"a": 1, "b": 1})
    assert ab_select("x", {"a": 1, "b": 3}) in {"a", "b"}
