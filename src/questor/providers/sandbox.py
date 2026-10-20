"""L5 SandboxPort adapters（ADR-0015；design/03 §4）。

后端 detection 只报告事实，不假装未实现的隔离。Windows Job Object 是 partial：进程树可终止，
但没有文件系统写围栏；seatbelt/bwrap 的实机执行到后续平台任务再验，这里可诚实返回 descriptor。
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
from collections.abc import Callable

from questor.contracts.ports import SandboxPort
from questor.contracts.sandbox import Confinement, SandboxBackend, SandboxDescriptor

_log = logging.getLogger("questor.sandbox")


class NullSandbox(SandboxPort):
    """无任何隔离能力的显式后端；用于让 capability floor 做 fail-closed 判断。"""

    def describe(self) -> SandboxDescriptor:
        return SandboxDescriptor(
            backend=SandboxBackend.NONE,
            confinement=Confinement.NONE,
            fences_writes=False,
            fences_network=False,
            isolates_process_tree=False,
            limitation="no sandbox backend available; exec is denied and write requires manual approval",
        )

    def fences_writes(self) -> bool:
        return False

    def fences_network(self) -> bool:
        return False

    def isolates_process_tree(self) -> bool:
        return False

    def wrap_argv(
        self,
        capability: str,
        argv: tuple[str, ...],
        *,
        workspace_root: str | None = None,
        cwd: str | None = None,
    ) -> tuple[str, ...]:
        raise NotImplementedError("NullSandbox cannot wrap argv; capability floor must deny or ask before this is called")

    def wrap_shell(
        self,
        capability: str,
        command: str,
        *,
        workspace_root: str | None = None,
        cwd: str | None = None,
    ) -> tuple[str, ...]:
        raise NotImplementedError("NullSandbox cannot wrap a shell command; the capability floor must deny or ask first")


class WindowsJobSandbox(SandboxPort):
    """Windows Job Object：仅承诺进程树终止，不承诺文件系统写围栏。"""

    def describe(self) -> SandboxDescriptor:
        return SandboxDescriptor(
            backend=SandboxBackend.JOB,
            confinement=Confinement.PARTIAL,
            fences_writes=False,
            fences_network=False,
            isolates_process_tree=True,
            limitation="Windows Job Object isolates and terminates the process tree but does not fence writes",
        )

    def fences_writes(self) -> bool:
        return False

    def fences_network(self) -> bool:
        return False

    def isolates_process_tree(self) -> bool:
        return True

    def wrap_argv(
        self,
        capability: str,
        argv: tuple[str, ...],
        *,
        workspace_root: str | None = None,
        cwd: str | None = None,
    ) -> tuple[str, ...]:
        # Job assignment happens inside ProcessRunner; argv itself must not be
        # silently rewritten into an unconfined shell string.
        return argv

    def wrap_shell(
        self,
        capability: str,
        command: str,
        *,
        workspace_root: str | None = None,
        cwd: str | None = None,
    ) -> tuple[str, ...]:
        """Job Object 只隔进程树，不隔文件/网络；把命令串拼回 shell 执行会失去 argv 边界。

        因此不提供“壳层包装”便利：shell 工具必须自己给出结构化 argv（ADR-0017/0018）。
        """
        raise NotImplementedError("Windows Job Object does not wrap shell strings; pass a structured argv via wrap_argv instead")


def _seatbelt_sandbox() -> SandboxPort:
    """macOS seatbelt：已探测到可执行文件，但 profile/包装尚未实机落地。"""
    return _UnimplementedSandbox(
        SandboxDescriptor(
            backend=SandboxBackend.SEATBELT,
            confinement=Confinement.PARTIAL,
            fences_writes=False,
            fences_network=False,
            isolates_process_tree=False,
            limitation="seatbelt detected; profile generation lands with POSIX process execution",
            executable_path="/usr/bin/sandbox-exec",
        )
    )


def _bwrap_sandbox(executable: str) -> SandboxPort:
    """Linux bubblewrap：同上，诚实报告“探到但未包装”。"""
    return _UnimplementedSandbox(
        SandboxDescriptor(
            backend=SandboxBackend.BWRAP,
            confinement=Confinement.PARTIAL,
            fences_writes=False,
            fences_network=False,
            isolates_process_tree=False,
            limitation="bubblewrap detected; profile generation lands with POSIX process execution",
            executable_path=executable,
        )
    )


def detect_sandbox() -> SandboxPort:
    """返回当前主机可证明使用的后端；不猜测、不 passthrough。"""
    if platform.system() == "Windows":
        return WindowsJobSandbox()
    if platform.system() == "Darwin" and os.path.exists("/usr/bin/sandbox-exec"):
        return _seatbelt_sandbox()
    bwrap = shutil.which("bwrap")
    if platform.system() == "Linux" and bwrap and os.path.isabs(bwrap):
        return _bwrap_sandbox(bwrap)
    return NullSandbox()


def backend_available(
    backend: SandboxBackend,
    *,
    system: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
    path_exists: Callable[[str], bool] = os.path.exists,
) -> bool:
    """该后端在**本主机**是否真实存在（选择器的硬前置；不存在即不得选中）。"""
    host = system or platform.system()
    if backend is SandboxBackend.JOB:
        return host == "Windows"
    if backend is SandboxBackend.SEATBELT:
        return host == "Darwin" and path_exists("/usr/bin/sandbox-exec")
    if backend is SandboxBackend.BWRAP:
        found = which("bwrap")
        return host == "Linux" and bool(found)
    if backend is SandboxBackend.NONE:
        return True
    return False


def select_sandbox(
    requested: str | None,
    *,
    system: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
    path_exists: Callable[[str], bool] = os.path.exists,
) -> SandboxPort:
    """只选后端、**绝不放宽 fail-closed**（OPT-7；吸收 codex "一次只选一维"）。

    - ``requested`` 为空→ :func:`detect_sandbox`（现行为逐字不变）；
    - 名字不可识别 / 本主机不存在→ :class:`NullSandbox`（比“猜一个”更严：capability floor
      会在无隔离事实时 deny/ask）；刻意不提供任何“绕过首次尝试”的开关；
    - 与探测结果一致→ 直接用探测结果（默认路径零行为变更）；
    - 其余合法且可用的名字→ 返回该后端的诚实描述（seatbelt/bwrap 仍报“探到未包装”）。
    """
    detected = detect_sandbox()
    raw = (requested or "").strip().lower()
    if not raw:
        return detected
    if raw == detected.describe().backend.value:
        return detected
    try:
        backend = SandboxBackend(raw)
    except ValueError:
        _log.warning("unknown sandbox backend %r requested; falling back to NullSandbox (fail-closed)", requested)
        return NullSandbox()
    if not backend_available(backend, system=system, which=which, path_exists=path_exists):
        _log.warning("sandbox backend %r is not available on this host; falling back to NullSandbox", backend.value)
        return NullSandbox()
    if backend is SandboxBackend.JOB:
        return WindowsJobSandbox()
    if backend is SandboxBackend.NONE:
        return NullSandbox()
    if backend is SandboxBackend.SEATBELT:
        return _seatbelt_sandbox()
    return _bwrap_sandbox(which("bwrap") or "bwrap")


class _UnimplementedSandbox(SandboxPort):
    """探测到后端但尚未实机包装时的诚实占位。"""

    def __init__(self, descriptor: SandboxDescriptor) -> None:
        self._descriptor = descriptor

    def describe(self) -> SandboxDescriptor:
        return self._descriptor

    def fences_writes(self) -> bool:
        return self._descriptor.fences_writes

    def fences_network(self) -> bool:
        return self._descriptor.fences_network

    def isolates_process_tree(self) -> bool:
        return self._descriptor.isolates_process_tree

    def wrap_argv(
        self,
        capability: str,
        argv: tuple[str, ...],
        *,
        workspace_root: str | None = None,
        cwd: str | None = None,
    ) -> tuple[str, ...]:
        raise NotImplementedError(f"{self._descriptor.backend.value} profile wrapping is not implemented yet")

    def wrap_shell(
        self,
        capability: str,
        command: str,
        *,
        workspace_root: str | None = None,
        cwd: str | None = None,
    ) -> tuple[str, ...]:
        raise NotImplementedError(f"{self._descriptor.backend.value} shell wrapping is not implemented yet")


__all__ = ["NullSandbox", "WindowsJobSandbox", "backend_available", "detect_sandbox", "select_sandbox"]
