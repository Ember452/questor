"""回环宿主的凭据五件套：随机端口、一次性 token、HttpOnly cookie、Host/Origin 校验、父租约。

token 只在进程内存里存在，永不读配置、永不落盘。
"""

from __future__ import annotations

import asyncio
import os
import secrets
import sys
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final

from questorharness.bootstrap.hosts.serve import refusals

COOKIE_NAME: Final[str] = "questor_launch"
CLIENT_COOKIE: Final[str] = "questor_client"
CLIENT_HEADER: Final[str] = "X-Questor-Client"
ALLOWED_HOSTNAMES: Final[frozenset[str]] = frozenset({"127.0.0.1", "localhost"})
TOKEN_MIN_BYTES: Final[int] = 32


@dataclass(frozen=True)
class LaunchCredential:
    """一次性启动凭据。"""

    token: str

    @classmethod
    def issue(cls) -> LaunchCredential:
        """生成 ≥32 字节的随机 token（urlsafe，便于握手行传输）。"""
        return cls(secrets.token_urlsafe(TOKEN_MIN_BYTES))


def cookie_header(token: str) -> str:
    """种植凭据用的 Set-Cookie 值。"""
    return f"{COOKIE_NAME}={token}; HttpOnly; SameSite=Strict; Path=/"


def client_cookie(client_id: str) -> str:
    """客户端身份 cookie：首次请求种植后，后续请求（含无 header 的 GET）可复用。"""
    return f"{CLIENT_COOKIE}={client_id}; HttpOnly; SameSite=Strict; Path=/"


def _hostname(value: str) -> str:
    """从 Host/Origin 里取出 hostname（去掉端口与 scheme）。"""
    without_scheme = value.split("://", 1)[-1]
    return without_scheme.split("/", 1)[0].rsplit(":", 1)[0].lower()


def validate_host(value: str | None) -> None:
    """Host 必须落在回环主机名上。"""
    if not value or _hostname(value) not in ALLOWED_HOSTNAMES:
        raise refusals.Refusal(refusals.AUTH_HOST, f"host not allowed: {value!r}", status=403)


def validate_origin(value: str | None) -> None:
    """Origin 必须落在回环主机名上；缺省按拒绝处理。"""
    if not value or _hostname(value) not in ALLOWED_HOSTNAMES:
        raise refusals.Refusal(refusals.AUTH_ORIGIN, f"origin not allowed: {value!r}", status=403)


def validate_cookie(cookies: Mapping[str, str], credential: LaunchCredential) -> None:
    """cookie 里的 token 必须与本次启动凭据一致。"""
    provided = cookies.get(COOKIE_NAME, "")
    if not provided or not secrets.compare_digest(provided, credential.token):
        raise refusals.Refusal(refusals.AUTH_REQUIRED, "launch credential required", status=401)


def handshake_payload(port: int, credential: LaunchCredential) -> bytes:
    """父进程握手行：单行 JSON，父进程读首个换行。"""
    return ('{"port":' + str(port) + ',"token":"' + credential.token + '"}').encode("utf-8")


class ParentLease:
    """父进程租约：stdin EOF 或父 pid 变化即视为父进程已退出。"""

    def __init__(self, on_exit: Callable[[], None]) -> None:
        self._on_exit = on_exit
        self._parent_pid = os.getppid()
        self._thread: threading.Thread | None = None
        self._stopped = threading.Event()
        self._fired = False
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self) -> None:
        """启动 stdin EOF 探针；记住事件循环以便工作线程安全唤醒。"""
        self._loop = asyncio.get_running_loop()
        self._thread = threading.Thread(
            target=self._watch_stdin, name="serve-parent-lease", daemon=True
        )
        self._thread.start()

    def _watch_stdin(self) -> None:
        """阻塞读 stdin；EOF 时触发退出回调。"""
        try:
            while not self._stopped.is_set():
                chunk = sys.stdin.readline()
                if chunk == "":
                    self._fire()
                    return
        except (OSError, ValueError):
            self._fire()

    def _fire(self) -> None:
        """只触发一次退出回调（工作线程 → 事件循环线程安全调度）。"""
        if self._fired:
            return
        self._fired = True
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self._on_exit)
        else:
            self._on_exit()

    async def watch_parent(self, interval: float = 0.5) -> None:
        """轮询父 pid；父进程消失即触发退出回调。"""
        while not self._stopped.is_set():
            if os.getppid() != self._parent_pid:
                self._fire()
                return
            await asyncio.sleep(interval)

    def stop(self) -> None:
        """停止探针（close 时调用）。"""
        self._stopped.set()
