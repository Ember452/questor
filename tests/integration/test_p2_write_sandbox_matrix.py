"""Permission + capability floor 全矩阵（ADR-0015）。"""

from __future__ import annotations

import pytest

from questor.contracts.permission import PermissionDecision
from questor.contracts.sandbox import Confinement, SandboxBackend, SandboxDescriptor
from questor.contracts.state_schema import ToolArgsStatus
from questor.contracts.tool import Capability, Risk, ToolSpec
from questor.kernel.permission_policy import PermissionEvaluation, evaluate_permission
from questor.state.domain_state import PermissionCtx


def _descriptor(backend: SandboxBackend, *, writes: bool, network: bool, process: bool) -> SandboxDescriptor:
    confinement = Confinement.FULL if backend in {SandboxBackend.SEATBELT, SandboxBackend.BWRAP} else Confinement.PARTIAL if backend is not SandboxBackend.NONE else Confinement.NONE
    return SandboxDescriptor(
        backend=backend,
        confinement=confinement,
        fences_writes=writes,
        fences_network=network,
        isolates_process_tree=process,
        limitation=f"{backend.value} matrix descriptor",
    )


def _evaluate(backend: SandboxBackend, capability: Capability, mode: str, approval_policy: str) -> PermissionDecision:
    writes = network = process = backend in {SandboxBackend.SEATBELT, SandboxBackend.BWRAP}
    if backend is SandboxBackend.JOB:
        writes = False
        network = False
        process = True
    spec = ToolSpec(
        name=capability.value,
        description="sandbox matrix test tool",
        params={"type": "object"},
        capability=capability,
        risk=Risk.HIGH if capability is Capability.EXEC else Risk.MEDIUM,
        read_only=capability is Capability.READONLY,
    )
    return (
        evaluate_permission(
            PermissionEvaluation(
                tool_name=spec.name,
                tool_spec=spec,
                args_status=ToolArgsStatus.VALID,
                arguments={"path": "inside-workspace"},
                permission=PermissionCtx(mode=mode, approval_policy=approval_policy),
                sandbox=_descriptor(backend, writes=writes, network=network, process=process),
            )
        ).decision
    )


@pytest.mark.parametrize("mode", ["default", "full_auto"])
def test_none_backend_exec_is_denied_under_every_mode(mode: str) -> None:
    assert _evaluate(SandboxBackend.NONE, Capability.EXEC, mode, "on_request") is PermissionDecision.DENY


@pytest.mark.parametrize("mode", ["default", "full_auto"])
def test_unfenced_write_always_requires_approval(mode: str) -> None:
    for backend in (SandboxBackend.NONE, SandboxBackend.JOB):
        assert _evaluate(backend, Capability.WRITE, mode, "on_request") is PermissionDecision.ASK


@pytest.mark.parametrize("mode", ["default", "full_auto"])
def test_unfenced_network_is_denied(mode: str) -> None:
    for backend in (SandboxBackend.NONE, SandboxBackend.JOB):
        assert _evaluate(backend, Capability.NETWORK, mode, "on_request") is PermissionDecision.DENY


def test_approval_policy_never_cannot_turn_capability_ask_into_allow() -> None:
    assert _evaluate(SandboxBackend.JOB, Capability.WRITE, "full_auto", "never") is PermissionDecision.DENY
