"""真实 Windows PowerShell 进程树超时清理（ADR-0018；T12）。"""

from __future__ import annotations

import asyncio
import base64
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from questor.contracts.process import ProcessRequest
from questor.contracts.sandbox import SandboxBackend
from questor.contracts.tool import Capability
from questor.providers.process_runner import SandboxedProcessRunner
from questor.providers.sandbox import WindowsJobSandbox

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or shutil.which("powershell.exe") is None,
    reason="real process-tree cleanup requires Windows powershell.exe",
)


def _encoded_command(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def _process_alive(pid: int) -> bool:
    output = subprocess.check_output(["tasklist", "/FI", f"PID eq {pid}", "/NH"], text=True)
    return str(pid) in output


async def test_powershell_timeout_kills_parent_and_child(tmp_path: Path) -> None:
    parent_file = tmp_path / "parent.txt"
    child_file = tmp_path / "child.txt"
    script = f"""
$parent = $PID
$parent | Out-File -FilePath '{parent_file}' -Encoding ascii
$child = Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-WindowStyle','Hidden','-Command','Start-Sleep 30') -PassThru
$child.Id | Out-File -FilePath '{child_file}' -Encoding ascii
Start-Sleep 30
"""
    powershell = Path(shutil.which("powershell.exe")).resolve()
    request = ProcessRequest(
        capability=Capability.EXEC,
        argv=(str(powershell), "-NoProfile", "-NonInteractive", "-EncodedCommand", _encoded_command(script)),
        cwd=tmp_path,
        timeout_s=2,
    )
    result = await SandboxedProcessRunner(WindowsJobSandbox()).run(request)
    assert result.timed_out is True
    assert result.sandbox_backend == SandboxBackend.JOB.value

    await asyncio.sleep(0.25)
    parent_pid = int(parent_file.read_text(encoding="ascii").strip())
    child_pid = int(child_file.read_text(encoding="ascii").strip())
    deadline = asyncio.get_running_loop().time() + 5
    while asyncio.get_running_loop().time() < deadline:
        if not _process_alive(parent_pid) and not _process_alive(child_pid):
            break
        await asyncio.sleep(0.1)
    else:
        pytest.fail(f"process tree survived timeout: parent={parent_pid} alive={_process_alive(parent_pid)} child={child_pid} alive={_process_alive(child_pid)}")
