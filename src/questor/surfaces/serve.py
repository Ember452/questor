"""L6 sidecar serve 生产入口 —— HTTP+SSE 服务挂上 uvicorn（ADR-0032 / D-P7-B；STRUCTURE S5）。

职责边界（**surfaces 零业务 S6**）：本模块只做"装配已构建好的 `EventServer` → 跑 uvicorn →
写进程握手 bootstrap"，**不 import 任何具体 store 实现**（`SQLiteStore`/`SQLiteMemoryStore` 的实例化
属组合根 `__main__.py --serve`，守 `check_layering_ast` FORBIDDEN_IMPORTS[surfaces] 与 C4）。

进程边界（ADR-0007/0032）：
- **只 bind `127.0.0.1`**（本地 IPC、无网络出口，呼应 C12），端口取 OS 分配的**临时口**（`:0`）；
- 先把 bound socket 的实际端口 + `generation` 落一份**本地 bootstrap 文件**（供 Rust 注入 webview、
  并作"重启后陈旧连接栅栏"的比对基），再以 `sockets=[sock]` 交给 uvicorn——**避免"起服务后再猜端口"的竞态**。

诚实边界：真 Rust 侧拉起/就绪探测/崩溃重启属 T8；本模块只提供 Python serve 面与其握手契约。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import secrets
import socket
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 仅类型；运行时由组合根传入，serve 不因此拉 fastapi/具体 store。
    from questor.surfaces.http_sse import EventServer

_log = logging.getLogger("questor.serve")

#: sidecar 唯一允许 bind 的 host：loopback。写 bootstrap 时也据此拒绝 0.0.0.0（进程边界红线）。
_LOOPBACK = "127.0.0.1"


def make_loopback_socket() -> tuple[socket.socket, int]:
    """绑一个 `127.0.0.1:0` 的 OS 临时口，返回 (已 bind 的 socket, 实际端口)。

    返回的 socket **未 listen**：交给 uvicorn 时由其完成监听（`Server.serve(sockets=[...])`）。
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((_LOOPBACK, 0))
    port = sock.getsockname()[1]
    return sock, port


def write_bootstrap(path: Path, *, host: str, port: int, generation: int, pid: int, token: str) -> dict[str, int | str]:
    """原子写 sidecar 握手 bootstrap（`{host, port, generation, pid, token}`）并返回该 dict。

    - 拒绝 `host != 127.0.0.1`：进程边界红线不因调用方笔误而破（C12/ADR-0032）。
    - 先写临时文件再 `replace`：Rust 侧不会读到半截 JSON（写一半被读会 JSONDecodeError）。
    - `token`：会话密钥，供壳/前端带在身上过端点鉴权（不泄到事件协议，仅本地启动握手）。
    """
    if host != _LOOPBACK:
        raise ValueError(f"sidecar bootstrap host 必须为 {_LOOPBACK!r}（本地 IPC），拒 {host!r}")
    data = {"host": host, "port": port, "generation": generation, "pid": pid, "token": token}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(path)
    return data


def read_bootstrap(path: Path) -> dict[str, int | str]:
    """回读 bootstrap（Python 侧自检/测试用；生产由 Rust 读，二者同一 JSON 契约）。"""
    return json.loads(Path(path).read_text(encoding="utf-8"))


async def serve(server: EventServer, *, generation: int, bootstrap_path: Path, static_dir: Path | None = None, token: str | None = None) -> dict[str, int | str]:
    """把 `EventServer` 挂上 uvicorn，bind loopback 临时口，先写 bootstrap 再常驻服务。

    依赖：`EventServer`（组合根已构建、已持 `StorePort` 抽象）；`generation` 由启动方（Rust 注入的
    env）分配并随 bootstrap 落盘，用于陈旧连接栅栏；`static_dir`（可选）为桌面前端产物，给定则
    由 sidecar 一并伺服，webview 直接指本服务根路径（ADR-0007）；`token` 为会话密钥（未给则自动生成），
    写入 bootstrap 供壳/前端取用并强制端点鉴权。返回写入的 bootstrap dict（仅在服务退出后可达）。
    失败语义：uvicorn 常驻直至被信号/关闭中断；期间任何 HTTP 错误由 FastAPI 侧按既有映射出声。
    """
    # 延迟 import：uvicorn 属 dev/打包依赖（非 core），serve 面才需要；`create_app` 同层、避免模块期拉 fastapi。
    import uvicorn

    from questor.surfaces.http_sse import create_app

    if token is None:
        token = secrets.token_urlsafe(24)  # 安全默认：--serve 总是启用会话 token，防本机任意进程旁路 HITL。

    app = create_app(server, static_dir=static_dir, token=token)
    sock, port = make_loopback_socket()
    boot = write_bootstrap(bootstrap_path, host=_LOOPBACK, port=port, generation=generation, pid=os.getpid(), token=token)
    # 起手一条一方记录钉住"serve 面已就绪"（DoD A①：起手即有日志，由一方记录兑现）。
    _log.info("sidecar serve ready host=%s port=%s generation=%s", _LOOPBACK, port, generation)
    config = uvicorn.Config(app, log_level="warning", access_log=False)
    uv_server = uvicorn.Server(config)

    async def _watch_shutdown() -> None:
        # 收到 /shutdown 信号 → 置 should_exit，uvicorn 优雅收尾在途请求后停机（不等壳的 grace 硬杀）。
        await server.shutdown_event.wait()
        uv_server.should_exit = True

    watcher = asyncio.create_task(_watch_shutdown())
    scheduler_task = asyncio.create_task(server.run_scheduler()) if server.scheduler is not None else None
    try:
        await uv_server.serve(sockets=[sock])
    finally:
        watcher.cancel()
        if scheduler_task is not None:
            scheduler_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await scheduler_task
        sock.close()
    return boot
