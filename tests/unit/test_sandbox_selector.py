"""OPT-7：sandbox_selector 只选后端、绝不放宽 fail-closed（`test_sandbox_gate` 三断言不受影响）。"""

from __future__ import annotations

from questor.contracts.sandbox import SandboxBackend
from questor.providers.sandbox import NullSandbox, backend_available, detect_sandbox, select_sandbox


def test_no_request_reproduces_detection_byte_for_byte() -> None:
    for requested in (None, "", "   "):
        assert select_sandbox(requested).describe() == detect_sandbox().describe()


def test_requesting_the_detected_backend_is_a_no_op() -> None:
    detected = detect_sandbox().describe().backend.value
    assert select_sandbox(detected).describe() == detect_sandbox().describe()


def test_unknown_backend_falls_back_to_null_not_a_guess() -> None:
    assert isinstance(select_sandbox("bypass-sandbox-first-attempt"), NullSandbox)


def test_unavailable_backend_falls_back_to_null() -> None:
    sandbox = select_sandbox("bwrap", system="Windows", which=lambda _name: None)
    assert isinstance(sandbox, NullSandbox)


def test_requesting_none_is_still_no_isolation_claim() -> None:
    sandbox = select_sandbox("none")
    assert isinstance(sandbox, NullSandbox)
    descriptor = sandbox.describe()
    assert descriptor.backend is SandboxBackend.NONE
    assert not descriptor.fences_writes and not descriptor.fences_network


def test_available_posix_backend_reports_honest_partial() -> None:
    sandbox = select_sandbox("bwrap", system="Linux", which=lambda _name: "/usr/bin/bwrap")
    descriptor = sandbox.describe()
    assert descriptor.backend is SandboxBackend.BWRAP
    # 选择器不得把“探到 bwrap”写成“有写围栏”：能力事实仍是 False。
    assert not descriptor.fences_writes
    assert not descriptor.fences_network
    assert backend_available(SandboxBackend.BWRAP, system="Linux", which=lambda _name: "/usr/bin/bwrap")
    assert not backend_available(SandboxBackend.JOB, system="Linux", which=lambda _name: None)
