"""T16 DoD：真实 powershell 工具（Windows 主验收；POSIX 无则 skip 报告，不 fake 冒充）。"""

from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

import pytest

from questor.capabilities.tools.powershell import PowerShellTool
from questor.kernel.loop import _ToolCtx
from questor.providers.process_runner import SandboxedProcessRunner
from questor.providers.sandbox import NullSandbox, WindowsJobSandbox

pytestmark = pytest.mark.skipif(shutil.which("powershell") is None and shutil.which("pwsh") is None, reason="no PowerShell on this host")


def _runner(tmp_path: Path) -> SandboxedProcessRunner:
    sandbox = WindowsJobSandbox() if sys.platform == "win32" else NullSandbox()
    return SandboxedProcessRunner(sandbox, data_root=tmp_path)


async def test_powershell_read_only_lists_workspace(tmp_path: Path) -> None:
    (tmp_path / "note.txt").write_text("hi", encoding="utf-8")
    ctx = _ToolCtx(tmp_path, asyncio.Event(), run_id="run-ps", process_runner=_runner(tmp_path))
    res = await PowerShellTool().execute({"command": "Get-ChildItem -Name"}, ctx)
    assert res.status == "success"
    assert "note.txt" in res.result


async def test_powershell_write_then_verify(tmp_path: Path) -> None:
    ctx = _ToolCtx(tmp_path, asyncio.Event(), run_id="run-ps2", process_runner=_runner(tmp_path))
    cmd = "Set-Content -Path made.txt -Value created"
    res = await PowerShellTool().execute({"command": cmd, "timeout": 30}, ctx)
    assert res.status == "success"
    assert (tmp_path / "made.txt").exists()


async def test_powershell_timeout_kills_tree(tmp_path: Path) -> None:
    ctx = _ToolCtx(tmp_path, asyncio.Event(), run_id="run-ps3", process_runner=_runner(tmp_path))
    res = await PowerShellTool().execute({"command": "Start-Sleep -Seconds 5", "timeout": 1}, ctx)
    assert res.status == "error"
    assert "timed out" in res.result
