"""进程内 serve 宿主（框架无关的路由 + SSE 帧 + 单写者租约）。

只导出核心装配件；aiohttp 适配（`http_server`）与 Studio 入口（`studio`）
按需单独 import，避免 REPL 路径被动拉起 HTTP 依赖。
"""

from questorharness.bootstrap.hosts.serve.authority import Authority
from questorharness.bootstrap.hosts.serve.broadcaster import Broadcaster
from questorharness.bootstrap.hosts.serve.host import ServeHost
from questorharness.bootstrap.hosts.serve.routes import Router
from questorharness.bootstrap.hosts.serve.transport import MemoryTransport, Request, Response
from questorharness.bootstrap.hosts.serve.wire import WireEncoder

__all__ = [
    "Authority",
    "Broadcaster",
    "MemoryTransport",
    "Request",
    "Response",
    "Router",
    "ServeHost",
    "WireEncoder",
]
