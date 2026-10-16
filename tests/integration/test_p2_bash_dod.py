"""T16 DoD：bash 工具 —— 请求构造正确；真跑需要"有 bash" + "后端能 wrap argv"两个条件。

CI 的教训：GitHub ubuntu runner 上有真 bash，但 POSIX 侧沙箱 `wrap_argv` 尚未实现
（ADR-0015 后置），所以真 echo 只能 skip；而"包不住就必须拒绝执行"这条**在所有平台都真跑**。
Windows 无 bash 时 `available=False`，不得被 provider 看到或误执行。
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

import pytest

from questor.capabilities.tools.bash import BashTool
from questor.contracts.ports import SandboxPort
from questor.contracts.process import ProcessResult
from questor.contracts.tool import Capability
from questor.kernel.loop import _ToolCtx
from questor.providers.process_runner import SandboxedProcessRunner
from questor.providers.sandbox import NullSandbox, detect_sandbox

_BASH = shutil.which("bash")


class _RecordingRunner:
    def __init__(self) -> None:
        self.last = None

    async def run(self, request):
        self.last = request
        return ProcessResult(exit_code=0, stdout_text="hello\n", stderr_text="")


def _wrapping_backend() -> SandboxPort | None:
    """本机真能 wrap argv 的后端；包不住返回 None（不假装能跑）。"""
    sandbox = detect_sandbox()
    try:
        sandbox.wrap_argv("exec", (_BASH or "prog",), workspace_root=".", cwd=".")
    except Exception:  # noqa: BLE001 - NotImplementedError 等一律视为"跑不了"
        return None
    return sandbox


_BACKEND = _wrapping_backend()


async def test_bash_builds_absolute_argv_and_maps_result(tmp_path: Path) -> None:
    runner = _RecordingRunner()
    ctx = _ToolCtx(tmp_path, asyncio.Event(), run_id="r", process_runner=runner)
    if _BASH is None:
        # 无 bash 的机器（如 Windows 本机）：必须显式拒绝，不能静默跑到别的东西上。
        res = await BashTool().execute({"command": "echo hi"}, ctx)
        assert res.status == "error"
        assert "not available" in res.result
        assert runner.last is None  # 连 ProcessRequest 都没构造，谈不上 spawn
        return
    res = await BashTool().execute({"command": "echo hi"}, ctx)
    assert res.status == "success"
    assert runner.last is not None
    assert Path(runner.last.argv[0]).is_absolute()
    assert runner.last.argv[1:] == ("-lc", "echo hi")
    assert runner.last.capability is Capability.EXEC
    assert "hello" in res.result


async def test_bash_empty_command_errors(tmp_path: Path) -> None:
    ctx = _ToolCtx(tmp_path, asyncio.Event(), process_runner=_RecordingRunner())
    res = await BashTool().execute({"command": "   "}, ctx)
    assert res.status == "error"


def test_bash_available_matches_which() -> None:
    assert BashTool().available() == (_BASH is not None)


@pytest.mark.skipif(
    _BASH is None or _BACKEND is None,
    reason=(
        "bash 真机验收需同时具备 bash 与可 wrap argv 的沙箱后端；"
        "POSIX 的 seatbelt/bwrap wrapping 尚未实现（ADR-0015 后置），此处不 fake 冒充真跑"
    ),
)
async def test_bash_real_echo_when_backend_can_wrap(tmp_path: Path) -> None:
    assert _BACKEND is not None
    runner = SandboxedProcessRunner(_BACKEND, data_root=tmp_path)
    ctx = _ToolCtx(tmp_path, asyncio.Event(), run_id="posix", process_runner=runner)
    res = await BashTool().execute({"command": "echo questor-ok"}, ctx)
    assert res.status == "success"
    assert "questor-ok" in res.result


_FAIL_CLOSED = pytest.mark.skipif(
    not isinstance(detect_sandbox(), NullSandbox),
    reason="本机沙箱后端能 wrap argv，不适用「无围栏拒绝」这一分支",
)


@_FAIL_CLOSED
async def test_bash_fail_closed_when_backend_cannot_wrap(tmp_path: Path) -> None:
    """后端给不出安全包法时必须结构化拒绝，而不是退化成裸跑（ADR-0015/C8）。"""
    if _BASH is None:
        pytest.skip("本机无 bash，拒绝分支由上一条测试覆盖")
    ctx = _ToolCtx(tmp_path, asyncio.Event(), run_id="fc", process_runner=SandboxedProcessRunner(NullSandbox(), data_root=tmp_path))
    res = await BashTool().execute({"command": "echo should-not-run", "timeout": 5}, ctx)
    assert res.status == "error"
    assert "sandbox wrapping failed" in res.result


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX 分相：验证 Linux/macOS 上的能力现状")
async def test_bash_posix_wrapping_still_unimplemented() -> None:
    """防回归：哪天 POSIX wrapping 实现了，这条会红，提醒同步放开真机验收与 ADR-0015。"""
    assert _wrapping_backend() is None, "POSIX 已能 wrap argv —— 该更新 ADR-0015 与 DoD 分相了"
