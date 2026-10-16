"""Sandboxed ProcessRunner unit tests（ADR-0018）。"""

from __future__ import annotations

import sys
from pathlib import Path

from questor.contracts.artifacts import ArtifactRef
from questor.contracts.process import ProcessRequest, ProcessResult
from questor.contracts.sandbox import Confinement, SandboxBackend, SandboxDescriptor
from questor.contracts.tool import Capability
from questor.providers.process_runner import SandboxedProcessRunner


class _GoodSandbox:
    def describe(self) -> SandboxDescriptor:
        return SandboxDescriptor(
            backend=SandboxBackend.SEATBELT,
            confinement=Confinement.FULL,
            fences_writes=True,
            fences_network=True,
            isolates_process_tree=True,
            limitation="full test",
        )

    def wrap_argv(self, capability, argv, *, workspace_root=None, cwd=None):  # noqa: ANN001
        del capability, workspace_root, cwd
        return ("/sandbox-exec", *argv)


class _FakeStream:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def read(self, size: int) -> bytes:
        if not self._chunks:
            return b""
        chunk = self._chunks.pop(0)
        assert len(chunk) <= size
        return chunk


class _FakeProcess:
    def __init__(self, *, stdout: bytes, stderr: bytes, returncode: int) -> None:
        self.returncode = returncode
        self.pid = 12345
        self.stdout = _FakeStream([stdout] if stdout else [])
        self.stderr = _FakeStream([stderr] if stderr else [])
        self.killed = False

    async def wait(self) -> int:
        return self.returncode

    def kill(self) -> None:
        self.killed = True

    async def communicate(self):  # pragma: no cover - implementation may use wait after reading
        return b"", b""


def _request(program: str | None = None, **overrides):  # noqa: ANN003
    values = {
        "capability": Capability.EXEC,
        "argv": (program or sys.executable, "-c", "exit 0"),
        "cwd": Path.cwd(),
        "timeout_s": 1,
        "declared_env_names": (),
        "stdout_limit": 100,
        "stderr_limit": 100,
    }
    values.update(overrides)
    return ProcessRequest(**values)


async def test_process_runner_uses_sandbox_wrap_and_scrubs_env(monkeypatch) -> None:  # noqa: ANN001
    captured: dict[str, object] = {}

    async def fake_exec(*argv, cwd=None, env=None, **kwargs):  # noqa: ANN002, ANN003
        captured["argv"] = argv
        captured["cwd"] = cwd
        captured["env"] = env
        captured["kwargs"] = kwargs
        return _FakeProcess(stdout=b"hello\n", stderr=b"", returncode=0)

    monkeypatch.setattr("questor.providers.process_runner.asyncio.create_subprocess_exec", fake_exec)
    monkeypatch.setenv("PATH", str(Path.cwd()))
    monkeypatch.setenv("OPENAI_API_KEY", "never-forward")
    result = await SandboxedProcessRunner(_GoodSandbox()).run(_request())
    assert captured["argv"] == ("/sandbox-exec", sys.executable, "-c", "exit 0")
    assert "OPENAI_API_KEY" not in captured["env"]
    assert result.exit_code == 0
    assert result.stdout_text == "hello\n"
    assert result.sandbox_backend == "seatbelt"
    assert "OPENAI_API_KEY" in result.env_scrubbed


async def test_backend_wrap_failure_is_structured_error() -> None:
    class _BrokenSandbox(_GoodSandbox):
        def wrap_argv(self, capability, argv, *, workspace_root=None, cwd=None):  # noqa: ANN001
            raise RuntimeError("seatbelt profile failed")

    result = await SandboxedProcessRunner(_BrokenSandbox()).run(_request())
    assert isinstance(result, ProcessResult)
    assert result.exit_code is None
    assert result.error
    assert "seatbelt profile failed" in result.error


async def test_output_limit_uses_artifact_store(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    captured: dict[str, object] = {}

    async def fake_exec(*argv, cwd=None, env=None, **kwargs):  # noqa: ANN002, ANN003
        del argv, cwd, env, kwargs
        return _FakeProcess(stdout=b"x" * 2000, stderr=b"", returncode=0)

    class _Store:
        async def put_bytes(self, content: bytes, *, run_id: str, kind: str, media_type: str = "application/octet-stream") -> ArtifactRef:
            captured["bytes"] = content
            return ArtifactRef(artifact_id="a", sha256="b" * 64, total_bytes=len(content), kind=kind, media_type=media_type)

    monkeypatch.setattr("questor.providers.process_runner.asyncio.create_subprocess_exec", fake_exec)
    result = await SandboxedProcessRunner(_GoodSandbox(), artifact_store=_Store(), data_root=tmp_path).run(_request(stdout_limit=100))
    assert captured["bytes"] == b"x" * 2000
    assert result.stdout_artifact is not None
    assert len(result.stdout_text.encode()) <= 100
