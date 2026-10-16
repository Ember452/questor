"""T16 DoD：真实 powershell 工具。

真跑条件有两个，缺一不可：**本机有 PowerShell** 且 **本机的沙箱后端真能 wrap argv**。
第二个条件是 CI 教出来的教训：GitHub ubuntu runner 上装了 `pwsh`，但 POSIX 侧的
seatbelt/bwrap `wrap_argv` 尚未实现（ADR-0015 明确后置），NullSandbox 会 fail-closed 拒绝——
所以不能只看 `which("powershell")` 就宣称"真跑过了"，也不能反过来把"包不了"当成测试通过。

后端包不住时，这里断言的是**正确行为**：结构化 error、绝不裸跑（`_FAIL_CLOSED` 那条）。
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

import pytest

from questor.capabilities.tools.powershell import PowerShellTool
from questor.contracts.ports import SandboxPort
from questor.kernel.loop import _ToolCtx
from questor.providers.process_runner import SandboxedProcessRunner
from questor.providers.sandbox import NullSandbox, detect_sandbox

_POWERSHELL = shutil.which("pwsh") or shutil.which("powershell") or shutil.which("powershell.exe")


def _wrapping_backend() -> SandboxPort | None:
    """返回本机**真能 wrap argv** 的沙箱后端；包不住就返回 None（不假装能跑）。"""
    sandbox = detect_sandbox()
    try:
        sandbox.wrap_argv("exec", (_POWERSHELL or "prog",), workspace_root=".", cwd=".")
    except Exception:  # noqa: BLE001 - NotImplementedError/其它包装失败都归为"跑不了"
        return None
    return sandbox


_BACKEND = _wrapping_backend()

pytestmark = pytest.mark.skipif(
    _POWERSHELL is None or _BACKEND is None,
    reason=(
        "PowerShell 真机验收需同时具备 pwsh/powershell 与可 wrap argv 的沙箱后端；"
        "POSIX 的 seatbelt/bwrap wrapping 尚未实现（ADR-0015 后置），此处不 fake 冒充真跑"
    ),
)


def _runner(tmp_path: Path) -> SandboxedProcessRunner:
    assert _BACKEND is not None  # skipif 已保证；给类型检查一个证据
    return SandboxedProcessRunner(_BACKEND, data_root=tmp_path)


async def test_powershell_read_only_lists_workspace(tmp_path: Path) -> None:
    (tmp_path / "note.txt").write_text("hi", encoding="utf-8")
    ctx = _ToolCtx(tmp_path, asyncio.Event(), run_id="run-ps", process_runner=_runner(tmp_path))
    res = await PowerShellTool().execute({"command": "Get-ChildItem -Name"}, ctx)
    assert res.status == "success"
    assert "note.txt" in res.result


async def test_powershell_write_then_verify(tmp_path: Path) -> None:
    ctx = _ToolCtx(tmp_path, asyncio.Event(), run_id="run-ps2", process_runner=_runner(tmp_path))
    res = await PowerShellTool().execute({"command": "Set-Content -Path made.txt -Value created", "timeout": 30}, ctx)
    assert res.status == "success"
    assert (tmp_path / "made.txt").exists()


async def test_powershell_timeout_kills_tree(tmp_path: Path) -> None:
    ctx = _ToolCtx(tmp_path, asyncio.Event(), run_id="run-ps3", process_runner=_runner(tmp_path))
    res = await PowerShellTool().execute({"command": "Start-Sleep -Seconds 5", "timeout": 1}, ctx)
    assert res.status == "timed_out"  # 与“工具自己失败”可区分（C7/ADR-0016）
    assert "timed out" in res.result


# ---- 不 skip、每条 CI 都真跑：后端包不住时必须 fail-closed ----

_FAIL_CLOSED = pytest.mark.skipif(
    not isinstance(detect_sandbox(), NullSandbox),
    reason="本机沙箱后端能 wrap argv，不适用「无围栏拒绝」这一分支",
)


@_FAIL_CLOSED
async def test_powershell_fail_closed_when_backend_cannot_wrap(tmp_path: Path) -> None:
    """NullSandbox 的 wrap_argv 故意 raise：工具必须回结构化 error，且绝不落到执行。"""
    made = tmp_path / "made.txt"
    ctx = _ToolCtx(tmp_path, asyncio.Event(), run_id="run-ps4", process_runner=SandboxedProcessRunner(NullSandbox(), data_root=tmp_path))
    res = await PowerShellTool().execute({"command": "Set-Content -Path made.txt -Value created", "timeout": 10}, ctx)
    assert res.status == "error"
    assert "sandbox wrapping failed" in res.result
    assert not made.exists()  # 拒绝发生在 spawn 之前，不是"跑了但报错"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX 分相：验证 Linux/macOS 上无后端时的拒绝")
async def test_powershell_backend_detection_is_honest_on_posix() -> None:
    """防回归：如果哪天 POSIX wrapping 实现了，这条会红，提醒同步放开上面的真机验收。"""
    assert _wrapping_backend() is None, "POSIX 已能 wrap argv —— 该更新 ADR-0015 与 DoD 分相了"
