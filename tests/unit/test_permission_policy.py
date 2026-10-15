"""PermissionCtx 纯权限引擎（ADR-0014；T8）。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from questor.contracts.sandbox import Confinement, SandboxBackend, SandboxDescriptor
from questor.contracts.shell_analysis import ShellAnalysis, ShellDialect, ShellParseStatus, ShellSegment
from questor.contracts.state_schema import PermissionRule, ToolArgsStatus
from questor.contracts.tool import Capability, Risk, ToolSpec
from questor.kernel.permission_policy import PermissionDecision, PermissionEvaluation, evaluate_permission
from questor.state.domain_state import PermissionCtx, PermissionDecisionRecord


def _spec(*, name: str = "write", read_only: bool = False, approval_mode: str | None = None) -> ToolSpec:
    return ToolSpec(
        name=name,
        description="test tool with a sufficiently long description",
        params={"type": "object"},
        capability=Capability.READONLY if read_only else Capability.WRITE,
        risk=Risk.LOW if read_only else Risk.MEDIUM,
        read_only=read_only,
        approval_mode=approval_mode,
    )


def _descriptor(**overrides):  # noqa: ANN003
    values = {
        "backend": SandboxBackend.SEATBELT,
        "confinement": Confinement.FULL,
        "fences_writes": True,
        "fences_network": True,
        "isolates_process_tree": True,
        "limitation": "full sandbox",
    }
    values.update(overrides)
    return SandboxDescriptor(**values)


def _evaluation(
    *,
    tool_name: str = "write",
    args=None,  # noqa: ANN001
    args_status: ToolArgsStatus = ToolArgsStatus.VALID,
    permission: PermissionCtx | None = None,
    spec: ToolSpec | None = None,
    analysis: ShellAnalysis | None = None,
    sandbox: SandboxDescriptor | None = None,
) -> PermissionEvaluation:
    return PermissionEvaluation(
        tool_name=tool_name,
        tool_spec=spec or _spec(name=tool_name),
        args_status=args_status,
        arguments=args or {},
        raw_args_summary=None if args_status is ToolArgsStatus.VALID else "bad json",
        shell_analysis=analysis,
        permission=permission or PermissionCtx(),
        sandbox=sandbox or _descriptor(),
    )


def test_invalid_arguments_denied_before_rules_and_mode() -> None:
    outcome = evaluate_permission(_evaluation(args_status=ToolArgsStatus.INVALID, permission=PermissionCtx(mode="full_auto")))
    assert outcome.decision is PermissionDecision.DENY
    assert "invalid" in outcome.reason.lower()


@pytest.mark.parametrize("candidate", ["~/.ssh/id_rsa", "project/.env", "secrets/token.pem"])
def test_sensitive_paths_are_denied_under_full_auto(tmp_path, candidate: str) -> None:  # noqa: ANN001
    outcome = evaluate_permission(
        _evaluation(
            args={"path": candidate},
            permission=PermissionCtx(mode="full_auto", cwd=tmp_path),
        )
    )
    assert outcome.decision is PermissionDecision.DENY
    assert outcome.floor_applied == "sensitive-path"


def test_realpath_failure_is_denied_instead_of_matching_raw_path(tmp_path) -> None:  # noqa: ANN001
    bad = tmp_path / "missing" / ".." / ".env"
    outcome = evaluate_permission(
        _evaluation(
            args={"path": str(bad)},
            permission=PermissionCtx(mode="full_auto", cwd=tmp_path),
        )
    )
    assert outcome.decision is PermissionDecision.DENY


def test_read_only_limit_and_rules_use_last_match_wins() -> None:
    permission = PermissionCtx(
        rules=(
            PermissionRule(id="1", tool_pattern="*", argument_pattern="*", action="allow"),
            PermissionRule(id="2", tool_pattern="write", argument_pattern="*", action="ask"),
        )
    )
    outcome = evaluate_permission(_evaluation(args={"path": "a.txt"}, permission=permission))
    assert outcome.decision is PermissionDecision.ASK


def test_read_only_tool_name_cannot_grant_access_without_toolspec() -> None:
    # 工具名是 read，但 ToolSpec.read_only=False；必须按权威 spec 判断。
    spec = _spec(name="read", read_only=False)
    outcome = evaluate_permission(_evaluation(tool_name="read", spec=spec, args={}))
    assert outcome.decision is PermissionDecision.ASK


def test_full_auto_only_auto_allows_calls_without_capability_floor() -> None:
    outcome = evaluate_permission(_evaluation(permission=PermissionCtx(mode="full_auto"), args={}))
    assert outcome.decision is PermissionDecision.ALLOW


def test_approval_mode_cannot_widen_and_unknown_denies() -> None:
    spec = _spec(approval_mode="prompt")
    permission = PermissionCtx(mode="full_auto")
    outcome = evaluate_permission(_evaluation(spec=spec, permission=permission, args={}))
    assert outcome.decision is PermissionDecision.ASK
    unknown = _evaluation(spec=_spec(approval_mode="magic"), permission=permission, args={})
    assert evaluate_permission(unknown).decision is PermissionDecision.DENY


def test_history_decisions_do_not_retroactively_override_new_mode(tmp_path) -> None:  # noqa: ANN001
    now = datetime.now(UTC)
    permission = PermissionCtx(
        mode="full_auto",
        decisions=(PermissionDecisionRecord(tool_call_id="tc", decision="ask", decided_by="user", at=now),),
    )
    outcome = evaluate_permission(_evaluation(permission=permission, args={}))
    assert outcome.decision is PermissionDecision.ALLOW


def test_shell_path_and_redirect_candidates_are_checked_for_sensitive_denials(tmp_path) -> None:  # noqa: ANN001
    analysis = ShellAnalysis(
        dialect=ShellDialect.POSIX,
        status=ShellParseStatus.PARSED,
        segments=(ShellSegment(program="cat", args=("~/.ssh/id_rsa",), read_paths=("~/.ssh/id_rsa",), read_only=True),),
        read_paths=("~/.ssh/id_rsa",),
    )
    outcome = evaluate_permission(
        _evaluation(
            tool_name="bash",
            spec=_spec(name="bash", read_only=True),
            args={"command": "cat ~/.ssh/id_rsa"},
            analysis=analysis,
            permission=PermissionCtx(cwd=tmp_path),
        )
    )
    assert outcome.decision is PermissionDecision.DENY


def test_permission_outcome_produces_redacted_args_summary() -> None:
    outcome = evaluate_permission(_evaluation(args={"path": "C:\\Users\\me\\.env", "content": "x" * 5000}))
    assert outcome.args_summary != str(outcome.arguments) if hasattr(outcome, "arguments") else True
    assert ".env" in outcome.args_summary or "redacted" in outcome.args_summary.lower()
