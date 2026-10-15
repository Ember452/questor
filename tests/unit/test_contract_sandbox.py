"""SandboxDescriptor 诚实性测试。"""

from __future__ import annotations

import pytest

from questor.contracts.sandbox import Confinement, SandboxBackend, SandboxDescriptor


def _descriptor(**overrides):  # noqa: ANN003, ANN202
    values = {
        "backend": SandboxBackend.NONE,
        "confinement": Confinement.NONE,
        "fences_writes": False,
        "fences_network": False,
        "isolates_process_tree": False,
        "limitation": "no sandbox backend available",
        "workspace_profile": {},
        "executable_path": None,
    }
    values.update(overrides)
    return SandboxDescriptor(**values)


def test_job_descriptor_cannot_claim_write_fence() -> None:
    descriptor = _descriptor(
        backend=SandboxBackend.JOB,
        confinement=Confinement.PARTIAL,
        isolates_process_tree=True,
        limitation="process-tree isolation only; no filesystem write fence",
    )
    assert descriptor.fences_writes is False
    with pytest.raises(ValueError, match="write fencing"):
        _descriptor(
            backend=SandboxBackend.JOB,
            confinement=Confinement.PARTIAL,
            fences_writes=True,
            isolates_process_tree=True,
            limitation="bad",
        )


def test_full_descriptor_requires_real_boundaries() -> None:
    with pytest.raises(ValueError, match="write fencing|must fence"):
        _descriptor(
            backend=SandboxBackend.SEATBELT,
            confinement=Confinement.FULL,
            fences_writes=False,
            isolates_process_tree=True,
            limitation="bad full claim",
        )


def test_none_descriptor_cannot_claim_capabilities() -> None:
    with pytest.raises(ValueError, match="cannot claim isolation"):
        _descriptor(fences_network=True, limitation="bad")
