"""P1 历史权限测试迁移到 PermissionCtx 纯引擎（ADR-0014）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from questor.contracts.sandbox import Confinement, SandboxBackend, SandboxDescriptor
from questor.contracts.state_schema import PermissionRule, ToolArgsStatus
from questor.contracts.tool import Capability, Risk, ToolSpec
from questor.kernel.permission_policy import PermissionDecision, PermissionEvaluation, evaluate_permission
from questor.state.domain_state import PermissionCtx


def _spec(*, name: str = "read", read_only: bool = True, approval_mode: str | None = None) -> ToolSpec:
    return ToolSpec(
        name=name,
        description="test permission tool",
        params={"type": "object"},
        capability=Capability.READONLY if read_only else Capability.WRITE,
        risk=Risk.LOW if read_only else Risk.MEDIUM,
        read_only=read_only,
        approval_mode=approval_mode,
    )


def _descriptor() -> SandboxDescriptor:
    return SandboxDescriptor(
        backend=SandboxBackend.SEATBELT,
        confinement=Confinement.FULL,
        fences_writes=True,
        fences_network=True,
        isolates_process_tree=True,
        limitation="test full sandbox",
    )


def _evaluation(name: str, args, *, permission=None, spec=None, args_status=ToolArgsStatus.VALID):  # noqa: ANN001
    return PermissionEvaluation(
        tool_name=name,
        tool_spec=spec or _spec(name=name, read_only=name == "read"),
        args_status=args_status,
        arguments=args or {},
        permission=permission or PermissionCtx(),
        sandbox=_descriptor(),
    )


def test_readonly_allowed_in_default_mode() -> None:
    assert evaluate_permission(_evaluation("read", {"file_path": "notes.txt"})).decision is PermissionDecision.ALLOW


def test_sensitive_path_denied_and_non_overridable(tmp_path: Path) -> None:
    permission = PermissionCtx(cwd=str(tmp_path), rules=(PermissionRule(id="r", tool_pattern="read", argument_pattern="*", action="allow"),))
    outcome = evaluate_permission(_evaluation("read", {"file_path": str(tmp_path / ".env")}, permission=permission))
    assert outcome.decision is PermissionDecision.DENY
    assert "non-overridable" in outcome.reason


def test_mutating_tool_asks_in_default_mode() -> None:
    outcome = evaluate_permission(_evaluation("bash", {"command": "ls"}, spec=_spec(name="bash", read_only=False)))
    assert outcome.decision is PermissionDecision.ASK


def test_plan_mode_denies_mutating_allows_read() -> None:
    permission = PermissionCtx(mode="plan")
    assert evaluate_permission(_evaluation("bash", {"command": "rm -rf x"}, permission=permission, spec=_spec(name="bash", read_only=False))).decision is PermissionDecision.DENY
    assert evaluate_permission(_evaluation("read", {"file_path": "a"}, permission=permission)).decision is PermissionDecision.ALLOW


def test_rule_last_match_wins() -> None:
    permission = PermissionCtx(
        rules=(
            PermissionRule(id="1", tool_pattern="bash", argument_pattern="*", action="ask"),
            PermissionRule(id="2", tool_pattern="bash", argument_pattern="echo *", action="allow"),
        )
    )
    outcome = evaluate_permission(_evaluation("bash", {"command": "echo hi"}, permission=permission, spec=_spec(name="bash", read_only=False)))
    assert outcome.decision is PermissionDecision.ALLOW


def test_never_policy_demotes_ask_to_deny() -> None:
    permission = PermissionCtx(approval_policy="never")
    outcome = evaluate_permission(_evaluation("write", {"file_path": "a.txt"}, permission=permission, spec=_spec(name="write", read_only=False)))
    assert outcome.decision is PermissionDecision.DENY
    assert "approval policy is never" in outcome.reason


@pytest.mark.parametrize("bad", ["", None])
def test_empty_argument_still_evaluates(bad: object) -> None:
    assert evaluate_permission(_evaluation("read", {} if bad is None else {"file_path": bad})).decision is PermissionDecision.ALLOW
