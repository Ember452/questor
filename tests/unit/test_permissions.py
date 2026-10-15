"""P1 T6 DoD — permission engine: sensitive deny, three-state, mode default, rules, never."""

from __future__ import annotations

import pytest

from questor.kernel.permissions import (
    ApprovalPolicy,
    DefaultPermissionEngine,
    PermissionDecision,
    PermissionMode,
    Rule,
)


def test_readonly_allowed_in_default_mode() -> None:
    eng = DefaultPermissionEngine(read_only_tools=frozenset({"read"}))
    decision, _ = eng.evaluate("read", {"file_path": "notes.txt"})
    assert decision == PermissionDecision.ALLOW


def test_sensitive_path_denied_and_non_overridable() -> None:
    eng = DefaultPermissionEngine(
        read_only_tools=frozenset({"read"}),
        rules=[Rule("read", "*", PermissionDecision.ALLOW.value)],  # a rule cannot lift denylist
    )
    decision, reason = eng.evaluate("read", {"file_path": ".env"})
    assert decision == PermissionDecision.DENY
    assert "denylist" in reason


def test_mutating_tool_asks_in_default_mode() -> None:
    eng = DefaultPermissionEngine()
    decision, _ = eng.evaluate("bash", {"command": "ls"})
    assert decision == PermissionDecision.ASK


def test_plan_mode_denies_mutating_allows_read() -> None:
    eng = DefaultPermissionEngine(mode=PermissionMode.PLAN, read_only_tools=frozenset({"read"}))
    assert eng.evaluate("bash", {"command": "rm -rf x"})[0] == PermissionDecision.DENY
    assert eng.evaluate("read", {"file_path": "a"})[0] == PermissionDecision.ALLOW


def test_rule_last_match_wins() -> None:
    eng = DefaultPermissionEngine(
        rules=[
            Rule("bash", "*", PermissionDecision.ASK),
            Rule("bash", "echo *", PermissionDecision.ALLOW),
        ]
    )
    assert eng.evaluate("bash", {"command": "echo hi"})[0] == PermissionDecision.ALLOW
    assert eng.evaluate("bash", {"command": "rm x"})[0] == PermissionDecision.ASK


def test_never_policy_demotes_ask_to_deny() -> None:
    eng = DefaultPermissionEngine(approval_policy=ApprovalPolicy.NEVER)
    decision, reason = eng.evaluate("write", {"file_path": "a.txt"})
    assert decision == PermissionDecision.DENY
    assert "never" in reason


@pytest.mark.parametrize("bad", ["", None])
def test_empty_argument_still_evaluates(bad: object) -> None:
    eng = DefaultPermissionEngine(read_only_tools=frozenset({"read"}))
    assert eng.evaluate("read", {} if bad is None else {"file_path": bad})[0] == PermissionDecision.ALLOW
