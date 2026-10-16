"""OS capability floor 高于 mode（ADR-0015；T9）。"""

from __future__ import annotations

import pytest

from questor.contracts.sandbox import Confinement, SandboxBackend, SandboxDescriptor
from questor.contracts.shell_analysis import ShellAnalysis, ShellDialect, ShellParseStatus, ShellSegment
from questor.contracts.tool import Capability, Risk, ToolSpec
from questor.kernel.capability_floor import apply_capability_floor


def _descriptor(backend: SandboxBackend, **capabilities) -> SandboxDescriptor:  # noqa: ANN003
    return SandboxDescriptor(
        backend=backend,
        confinement=capabilities.pop("confinement", Confinement.NONE if backend is SandboxBackend.NONE else Confinement.PARTIAL),
        fences_writes=capabilities.pop("fences_writes", False),
        fences_network=capabilities.pop("fences_network", False),
        isolates_process_tree=capabilities.pop("isolates_process_tree", False),
        limitation=capabilities.pop("limitation", f"{backend.value} capability probe"),
    )


def _spec(capability: Capability) -> ToolSpec:
    return ToolSpec(
        name=capability.value,
        description="capability floor test tool",
        params={"type": "object"},
        capability=capability,
        risk=Risk.HIGH if capability is Capability.EXEC else Risk.MEDIUM,
        read_only=capability is Capability.READONLY,
    )


def _read_only_analysis() -> ShellAnalysis:
    return ShellAnalysis(
        dialect=ShellDialect.POSIX,
        status=ShellParseStatus.PARSED,
        segments=(ShellSegment(program="ls", args=("target",), read_paths=("target",), read_only=True),),
        read_paths=("target",),
    )


@pytest.mark.parametrize(
    ("backend", "capability", "analysis", "expected_decision", "expected_floor"),
    [
        (SandboxBackend.NONE, Capability.EXEC, None, "deny", "exec-capability"),
        (SandboxBackend.NONE, Capability.WRITE, None, "ask", "write-capability"),
        (SandboxBackend.JOB, Capability.EXEC, None, "ask", "exec-capability"),
        (SandboxBackend.JOB, Capability.EXEC, _read_only_analysis(), "allow", None),
        (SandboxBackend.JOB, Capability.WRITE, None, "ask", "write-capability"),
        (SandboxBackend.SEATBELT, Capability.WRITE, None, "allow", None),
        (SandboxBackend.SEATBELT, Capability.EXEC, None, "allow", None),
    ],
)
def test_capability_floor_is_independent_of_mode(backend: SandboxBackend, capability: Capability, analysis, expected_decision: str, expected_floor: str | None) -> None:
    confinement = Confinement.NONE if backend is SandboxBackend.NONE else Confinement.FULL if backend in {SandboxBackend.SEATBELT, SandboxBackend.BWRAP} else Confinement.PARTIAL
    descriptor = _descriptor(
        backend,
        fences_writes=backend in {SandboxBackend.SEATBELT, SandboxBackend.BWRAP},
        fences_network=backend in {SandboxBackend.SEATBELT, SandboxBackend.BWRAP},
        isolates_process_tree=backend is not SandboxBackend.NONE,
        confinement=confinement,
    )
    outcome = apply_capability_floor(
        tool_spec=_spec(capability),
        sandbox=descriptor,
        shell_analysis=analysis,
        args_summary="test args",
        mode="full_auto",
    )
    assert outcome is not None or expected_decision == "allow"
    if outcome is not None:
        assert outcome.decision.value == expected_decision
        assert outcome.floor_applied == expected_floor
        if expected_decision == "ask":
            assert outcome.warnings
    else:
        assert expected_decision == "allow"


def test_capability_floor_never_allows_unsandboxed_exec_under_full_auto() -> None:
    outcome = apply_capability_floor(
        tool_spec=_spec(Capability.EXEC),
        sandbox=_descriptor(SandboxBackend.NONE),
        shell_analysis=_read_only_analysis(),
        args_summary="ls",
        mode="full_auto",
    )
    assert outcome is not None
    assert outcome.decision.value == "deny"
    assert "no sandbox" in outcome.reason.lower()


def test_network_without_fence_is_denied() -> None:
    outcome = apply_capability_floor(
        tool_spec=_spec(Capability.NETWORK),
        sandbox=_descriptor(SandboxBackend.JOB),
        shell_analysis=None,
        args_summary="fetch",
        mode="full_auto",
    )
    assert outcome is not None
    assert outcome.decision.value == "deny"
