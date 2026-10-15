"""ProcessRunner contracts。"""

from __future__ import annotations

from pathlib import Path

import pytest

from questor.contracts.process import ProcessRequest, ProcessResult, ProcessRunnerPort
from questor.contracts.tool import Capability


def test_process_request_rejects_relative_program_and_bad_limits() -> None:
    with pytest.raises(ValueError, match="absolute"):
        ProcessRequest(
            capability=Capability.EXEC,
            argv=("powershell", "-NoProfile"),
            cwd=Path.cwd(),
            timeout_s=1,
        )
    with pytest.raises(ValueError, match="positive"):
        ProcessRequest(
            capability=Capability.EXEC,
            argv=(str(Path("C:/Windows/System32/cmd.exe")),),
            cwd=Path.cwd(),
            timeout_s=0,
        )


def test_process_result_keeps_failure_facts_consistent() -> None:
    result = ProcessResult(exit_code=124, stdout_text="", stderr_text="", timed_out=True)
    assert result.timed_out is True
    with pytest.raises(ValueError, match="error ProcessResult"):
        ProcessResult(exit_code=1, stdout_text="", stderr_text="", error="launcher failed")


def test_process_runner_port_is_runtime_protocol() -> None:
    class _Runner:
        async def run(self, request):  # noqa: ANN001, ANN202
            return ProcessResult(exit_code=0, stdout_text="", stderr_text="")

    assert isinstance(_Runner(), ProcessRunnerPort)
