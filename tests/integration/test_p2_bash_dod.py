"""T16 DoD：bash 工具 —— 请求构造正确；Windows 缺 bash 时 available=False，不 fake 冒充真跑。"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from questor.capabilities.tools.bash import BashTool
from questor.contracts.process import ProcessResult
from questor.contracts.tool import Capability
from questor.kernel.loop import _ToolCtx

_BASH = shutil.which("bash")


class _RecordingRunner:
    def __init__(self) -> None:
        self.last = None

    async def run(self, request):
        self.last = request
        return ProcessResult(exit_code=0, stdout_text="hello\n", stderr_text="")


async def test_bash_builds_absolute_argv_and_maps_result(tmp_path: Path) -> None:
    runner = _RecordingRunner()
    ctx = _ToolCtx(tmp_path, asyncio.Event(), run_id="r", process_runner=runner)
    # 即使本机有/无 bash，execute 需要 which("bash")；缺失时走 unavailable 分支，单独测。
    if _BASH is None:
        res = await BashTool().execute({"command": "echo hi"}, ctx)
        assert res.status == "error"
        assert "not available" in res.result
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


async def test_bash_real_echo_on_posix(tmp_path: Path) -> None:
    if _BASH is None:
        return  # Windows 无 bash：不 fake 冒充真跑，只在 POSIX/CI 真验
    from questor.providers.process_runner import SandboxedProcessRunner
    from questor.providers.sandbox import detect_sandbox

    runner = SandboxedProcessRunner(detect_sandbox(), data_root=tmp_path)
    ctx = _ToolCtx(tmp_path, asyncio.Event(), run_id="posix", process_runner=runner)
    res = await BashTool().execute({"command": "echo questor-ok"}, ctx)
    assert res.status == "success"
    assert "questor-ok" in res.result
