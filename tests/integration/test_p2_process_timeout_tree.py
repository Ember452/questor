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


# 先等进程树真的起来，再让 deadline 到期去杀。
# CI 上首次拉起 PowerShell（含 AMSI/Defender 扫描）远慢于本机，固定短超时会让父/子 PID
# 根本来不及写出——那不是“清理失败”，而是“断言落空”（没子进程却声称杀了进程树）。
# 预算故意给宽（20s）：真上太慢的环境应该明说“没验到”，而不是误报成清理坏了。
_LAUNCH_BUDGET_S = 20.0
_RUN_TIMEOUT_S = 25.0


async def test_powershell_timeout_kills_parent_and_child(tmp_path: Path) -> None:
    parent_file = tmp_path / "parent.txt"
    child_file = tmp_path / "child.txt"
    script = f"""
$parent = $PID
$parent | Out-File -FilePath '{parent_file}' -Encoding ascii
$child = Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-WindowStyle','Hidden','-Command','Start-Sleep 120') -PassThru
$child.Id | Out-File -FilePath '{child_file}' -Encoding ascii
Start-Sleep 120
"""
    powershell = Path(shutil.which("powershell.exe")).resolve()
    request = ProcessRequest(
        capability=Capability.EXEC,
        argv=(str(powershell), "-NoProfile", "-NonInteractive", "-EncodedCommand", _encoded_command(script)),
        cwd=tmp_path,
        timeout_s=_RUN_TIMEOUT_S,
    )
    runner = asyncio.create_task(SandboxedProcessRunner(WindowsJobSandbox()).run(request))

    # 阶段一：等父子 PID 都写出（脚本先写父、后 spawn 子、再写子）——两者齐备才能证明“树”存在。
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _LAUNCH_BUDGET_S
    while not (parent_file.is_file() and child_file.is_file()):
        if runner.done():  # 跑完/报错都没写出 PID，属于环内异常，不等了
            break
        if loop.time() >= deadline:
            runner.cancel()
            pytest.fail(f"PowerShell 未能在 {_LAUNCH_BUDGET_S}s 内写出父/子 PID；进程树未建起，无法验证清理（不能拿空断言算通过）")
        await asyncio.sleep(0.1)

    if not (parent_file.is_file() and child_file.is_file()):
        # runner 提前结束或写入缺失：明确失败，不去读不存在的文件（那只会报 FileNotFoundError，
        # 掩盖“根本没验到进程树”这个真正结论）。
        runner.cancel()
        pytest.fail(f"进程树未完整建立：parent.txt={parent_file.is_file()} child.txt={child_file.is_file()}，无法验证超时清理")

    parent_pid = int(parent_file.read_text(encoding="ascii").strip())
    child_pid = int(child_file.read_text(encoding="ascii").strip())

    # 阶段二：由 Harness 自超时而非测试自杀，才能验到真实 kill 链（Job 终止 / taskkill 兜底）。
    result = await runner
    assert result.timed_out is True
    assert result.sandbox_backend == SandboxBackend.JOB.value

    # 阶段三：父子 PID 都必须消失（_process_alive 轮询，不是固定 sleep）。
    deadline = loop.time() + 10
    while loop.time() < deadline:
        if not _process_alive(parent_pid) and not _process_alive(child_pid):
            return
        await asyncio.sleep(0.2)
    pytest.fail(f"process tree survived timeout: parent={parent_pid} alive={_process_alive(parent_pid)} child={child_pid} alive={_process_alive(child_pid)}")
