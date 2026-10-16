"""L5 Harness-owned process runner（ADR-0018；HARD C1/C8/C10）。

工具不能自行 spawn。本 adapter 统一负责 sandbox wrapping、env scrub、cwd、timeout、
Windows Job Object、进程树终止、输出限额和 artifact 落盘。任一包装失败都返回结构化
ProcessResult，不执行未包装 argv。
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

from questor.contracts.artifacts import ArtifactRef
from questor.contracts.process import ProcessRequest, ProcessResult
from questor.contracts.sandbox import SandboxBackend, SandboxDescriptor
from questor.providers.env_safety import build_child_env, scrub_environment


class FileSystemArtifactWritePort:
    """仅声明 ProcessRunner 需要的 bytes artifact 写入能力。"""

    async def put_bytes(
        self,
        content: bytes,
        *,
        run_id: str,
        kind: str,
        media_type: str = "application/octet-stream",
    ) -> ArtifactRef: ...


class SandboxedProcessRunner:
    """默认 ProcessRunner adapter。"""

    def __init__(
        self,
        sandbox,  # noqa: ANN001
        *,
        artifact_store: FileSystemArtifactWritePort | None = None,
        data_root: Path | None = None,
        environment: dict[str, str] | None = None,
    ) -> None:
        self.sandbox = sandbox
        self.artifact_store = artifact_store
        self.data_root = data_root or Path.cwd()
        self.environment = environment

    async def run(self, request: ProcessRequest) -> ProcessResult:
        descriptor: SandboxDescriptor | None = None
        try:
            descriptor = self.sandbox.describe()
            wrapped = self.sandbox.wrap_argv(
                request.capability.value,
                request.argv,
                workspace_root=str(self.data_root),
                cwd=str(request.cwd),
            )
        except Exception as exc:  # noqa: BLE001 - launcher/profile failure must stay structured
            return ProcessResult(
                exit_code=None,
                stdout_text="",
                stderr_text="",
                sandbox_backend=descriptor.backend.value if descriptor else SandboxBackend.NONE.value,
                confinement=descriptor.confinement.value if descriptor else "none",
                warning=descriptor.limitation if descriptor else None,
                error=f"sandbox wrapping failed: {exc}",
            )

        base_env, scrubbed = scrub_environment(self.environment if self.environment is not None else os.environ)
        try:
            child_env = build_child_env(
                base_env,
                declared=request.declared_env_names,
                source_env=self.environment if self.environment is not None else os.environ,
            )
        except PermissionError as exc:
            return ProcessResult(
                exit_code=None,
                stdout_text="",
                stderr_text="",
                sandbox_backend=descriptor.backend.value,
                confinement=descriptor.confinement.value,
                warning=descriptor.limitation,
                env_scrubbed=scrubbed,
                error=str(exc),
            )

        kwargs: dict[str, object] = {
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
        }
        try:
            process = await asyncio.create_subprocess_exec(*wrapped, cwd=str(request.cwd), env=child_env, **kwargs)
        except Exception as exc:  # noqa: BLE001 - process launch failure is data, not a loop crash
            return ProcessResult(
                exit_code=None,
                stdout_text="",
                stderr_text="",
                sandbox_backend=descriptor.backend.value,
                confinement=descriptor.confinement.value,
                warning=descriptor.limitation,
                env_scrubbed=scrubbed,
                error=f"process launch failed: {exc}",
            )

        job = None
        if sys.platform == "win32" and descriptor.backend is SandboxBackend.JOB and process.pid is not None:
            # Job assignment can fail when the child inherits another Windows job. Process-tree
            # cleanup still works via taskkill /T; this remains partial, never a write fence.
            try:
                from questor.providers._win_job import WindowsJobObject

                job = WindowsJobObject()
                job.assign_pid(process.pid)
            except Exception:  # noqa: BLE001 - fallback below must still kill tree on timeout
                if job is not None:
                    job.close()
                    job = None

        timed_out = False
        try:
            stdout_text, stdout_artifact = await asyncio.wait_for(
                self._read_stream(process.stdout, request.stdout_limit, "stdout"),
                timeout=request.timeout_s,
            )
            stderr_text, stderr_artifact = await asyncio.wait_for(
                self._read_stream(process.stderr, request.stderr_limit, "stderr"),
                timeout=request.timeout_s,
            )
            exit_code = await asyncio.wait_for(process.wait(), timeout=request.timeout_s)
        except TimeoutError:
            timed_out = True
            if sys.platform == "win32" and process.pid is not None and job is None:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], check=False, capture_output=True)
            process.kill()
            exit_code = await process.wait()
            stdout_text, stdout_artifact = "", None
            stderr_text, stderr_artifact = "", None
        finally:
            if job is not None:
                job.close()

        warning = descriptor.limitation if descriptor.confinement.value != "full" else None
        return ProcessResult(
            exit_code=exit_code,
            stdout_text=stdout_text,
            stderr_text=stderr_text,
            timed_out=timed_out,
            process_tree_killed=timed_out,
            sandbox_backend=descriptor.backend.value,
            confinement=descriptor.confinement.value,
            warning=warning,
            env_scrubbed=scrubbed,
            stdout_artifact=stdout_artifact,
            stderr_artifact=stderr_artifact,
        )

    async def _read_stream(self, stream, limit: int, kind: str):  # noqa: ANN001, ANN201
        if stream is None:
            return "", None
        bounded: list[bytes] = []
        spool: bytearray | None = None
        total = 0
        while True:
            chunk = await stream.read(8192)
            if not chunk:
                break
            total += len(chunk)
            if spool is not None:
                spool.extend(chunk)
            elif total <= limit:
                bounded.append(chunk)
            else:
                spool = bytearray(b"".join(bounded))
                bounded.clear()
                spool.extend(chunk)

        if total <= limit:
            return b"".join(bounded).decode("utf-8", errors="replace"), None
        if spool is None:
            spool = bytearray(b"".join(bounded))
        if self.artifact_store is not None:
            ref = await self.artifact_store.put_bytes(
                bytes(spool),
                run_id=kind,
                kind=f"process-{kind}",
                media_type="text/plain",
            )
            return _bounded_preview(spool, limit), ref
        # 无 artifact store 时也不得把无界全文塞回 prompt；只保留有界 preview。
        return _bounded_preview(spool, limit), None


def _bounded_preview(spool: bytearray, limit: int) -> str:
    """取不超过 ``limit`` 字节的合法 UTF-8 前缀。

    直接 `spool[:limit].decode(errors="replace")` 会在多字节字符中间开刀，把裂口处
    渲染成一串 U+FFFD 噪声（CJK/emoji 输出下可见）；errors="ignore" 则把不完整尾字节丢弃，
    拿到的是合法前缀。
    """
    return bytes(spool[:limit]).decode("utf-8", errors="ignore")


__all__ = ["ProcessRequest", "ProcessResult", "SandboxedProcessRunner"]
