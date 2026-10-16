"""T16b：ToolContext 到 ProcessRunner/ArtifactStore 的接线（合并 declared env、内容寻址落盘）。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from questor.contracts.process import ProcessRequest, ProcessResult
from questor.contracts.tool import Capability
from questor.kernel.loop import _ToolCtx


class _RecordingRunner:
    def __init__(self) -> None:
        self.last: ProcessRequest | None = None

    async def run(self, request: ProcessRequest) -> ProcessResult:
        self.last = request
        return ProcessResult(exit_code=0, stdout_text="ok", stderr_text="")


class _RecordingStore:
    def __init__(self) -> None:
        self.calls: list[tuple[bytes, str, str]] = []

    async def put_bytes(self, content: bytes, *, run_id: str, kind: str, media_type: str = "application/octet-stream"):
        self.calls.append((content, run_id, kind))
        return f"artifact://{len(content)}"


def test_run_process_merges_declared_env_names(tmp_path: Path) -> None:
    runner = _RecordingRunner()
    ctx = _ToolCtx(tmp_path, asyncio.Event(), run_id="run1", process_runner=runner)
    ctx.declare_env_passthrough("TENOR_API_KEY")
    # argv[0] 必须是绝对路径：用 sys.executable（两平台都绝对），不能硬编码 Windows 路径。
    req = ProcessRequest(capability=Capability.EXEC, argv=(sys.executable,), cwd=tmp_path, timeout_s=5, declared_env_names=("PATH",))
    result = asyncio.run(ctx.run_process(req))
    assert result.exit_code == 0
    assert runner.last is not None
    assert set(runner.last.declared_env_names) >= {"PATH", "TENOR_API_KEY"}


def test_put_artifact_uses_store_and_run_id(tmp_path: Path) -> None:
    store = _RecordingStore()
    ctx = _ToolCtx(tmp_path, asyncio.Event(), run_id="run42", artifact_store=store)
    ref = asyncio.run(ctx.put_artifact(b"hello", kind="tool-stdout"))
    assert ref == "artifact://5"
    assert store.calls == [(b"hello", "run42", "tool-stdout")]


def test_run_process_without_runner_raises(tmp_path: Path) -> None:
    ctx = _ToolCtx(tmp_path, asyncio.Event())
    req = ProcessRequest(capability=Capability.EXEC, argv=(sys.executable,), cwd=tmp_path, timeout_s=1)
    try:
        asyncio.run(ctx.run_process(req))
    except RuntimeError as exc:
        assert "ProcessRunner" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected RuntimeError")
