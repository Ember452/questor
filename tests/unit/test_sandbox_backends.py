"""沙箱后端的诚实性契约（ADR-0015/0017；design/03 §4）。

后端宁可抛错也不能"假装包好了"：`wrap_shell` 目前在**所有**后端都不成立（Job 只隔进程树、
seatbelt/bwrap profile 未实现、Null 无任何隔离），所以这里钉两条：
1. 任何后端都不允许把 shell 命令串原样返回（那等于 passthrough 未隔离执行）；
2. descriptor 不得谎报围栏能力（confinement=full 才允许静默放行）。
"""

from __future__ import annotations

import pytest

from questor.contracts.sandbox import Confinement, SandboxBackend
from questor.providers.sandbox import NullSandbox, WindowsJobSandbox, detect_sandbox

_BACKENDS = {
    "null": NullSandbox(),
    "windows-job": WindowsJobSandbox(),
    "detected": detect_sandbox(),
}


@pytest.mark.parametrize(("name", "sandbox"), list(_BACKENDS.items()))
def test_wrap_shell_never_passes_a_shell_string_through(name: str, sandbox) -> None:  # noqa: ANN001
    """shell 串必须被拒绝或被真正包装；原样返回就是"未隔离却以为隔离了"。"""
    with pytest.raises(NotImplementedError):
        sandbox.wrap_shell("exec", "rm -rf /", workspace_root=".", cwd=".")


@pytest.mark.parametrize(("name", "sandbox"), list(_BACKENDS.items()))
def test_descriptor_never_claims_write_fence_it_lacks(name: str, sandbox) -> None:  # noqa: ANN001
    descriptor = sandbox.describe()
    if descriptor.backend is not SandboxBackend.SEATBELT and descriptor.backend is not SandboxBackend.BWRAP:
        assert descriptor.fences_writes is False, f"{name} 谎报写围栏"
    if descriptor.backend in {SandboxBackend.NONE, SandboxBackend.JOB}:
        assert descriptor.confinement is not Confinement.FULL, f"{name} 谎报 confinement=full"


def test_detected_backend_is_honest_on_this_host() -> None:
    """探测结果必须与实际能力一致：Windows 上是 job（隔进程树、不隔写）。"""
    descriptor = detect_sandbox().describe()
    assert descriptor.backend is not None
    if descriptor.backend is SandboxBackend.JOB:
        assert descriptor.isolates_process_tree is True
        assert descriptor.fences_writes is False
        assert descriptor.limitation  # 限制必须写清楚，不能只报"已隔离"
