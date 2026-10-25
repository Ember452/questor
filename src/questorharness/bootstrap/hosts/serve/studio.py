"""Studio 宿主：回环 TCP + 凭据五件套 + 握手行。

父进程（Electron/脚本）读 stdout 首行拿到端口与 token，再用 HttpOnly
cookie 种植凭据；stdin 关闭或父进程退出即服务失效。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from questorharness.bootstrap.hosts.serve import auth
from questorharness.bootstrap.hosts.serve.host import ServeHost
from questorharness.bootstrap.hosts.serve.http_server import HttpServer
from questorharness.bootstrap.hosts.terminal_client import (
    build_serve_host,
    default_profile_root,
)


def _web_dist() -> Path | None:
    """Electron 要加载的 web 构建产物：环境变量优先，其次仓内 apps/web/dist。"""
    override = os.environ.get("QUESTOR_WEB_DIST")
    if override:
        candidate = Path(override)
        return candidate if candidate.is_dir() else None
    repo = Path(__file__).resolve().parents[5]
    candidate = repo / "apps/web/dist"
    return candidate if candidate.is_dir() else None


async def run_studio_host(
    *,
    cwd: str | None = None,
    model: str | None = None,
    max_turns: int | None = None,
    effort: str | None = None,
    base_url: str | None = None,
    system_prompt: str | None = None,
    api_key: str | None = None,
    api_format: str | None = None,
    api_client: Any = None,
    permission_mode: str | None = None,
    profile_root: Path | None = None,
    profile_id: str = "coding",
    allow_no_auth: bool = False,
    overrides: dict[str, object] | None = None,
) -> int:
    """启动回环宿主并阻塞到父租约失效。"""
    host: ServeHost = await build_serve_host(
        cwd=cwd,
        model=model,
        max_turns=max_turns,
        effort=effort,
        base_url=base_url,
        system_prompt=system_prompt,
        api_key=api_key,
        api_format=api_format,
        api_client=api_client,
        permission_mode=permission_mode,
        profile_root=profile_root or default_profile_root(),
        profile_id=profile_id,
        overrides=overrides,
    )
    await host.start()
    credential = auth.LaunchCredential.issue()
    server = HttpServer(
        host.router, credential, allow_no_auth=allow_no_auth, static_root=_web_dist()
    )
    stop = asyncio.Event()
    lease = auth.ParentLease(stop.set)
    try:
        port = await server.start()
        sys.stdout.write(auth.handshake_payload(port, credential).decode("utf-8") + "\n")
        sys.stdout.flush()
        lease.start()
        watcher = asyncio.create_task(lease.watch_parent())
        try:
            await stop.wait()
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        return 0
    finally:
        lease.stop()
        await server.close()
        await host.close()
