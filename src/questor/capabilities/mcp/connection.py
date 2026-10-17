"""L3 MCP stdio 连接生命周期（C12/C13；ADR-0030：官方 `mcp` SDK v1）。

一个 server = 一个 transport + 一个 session，由 `AsyncExitStack` 拥有：`start()` 进入
`stdio_client` + `ClientSession` 并握手（`initialize`），`aclose()` 退出栈——SDK 负责关 stdin、
等进程退出、超时则升级杀进程树，**不留悬空子进程/流**（本仓非守护线程泄漏守卫会抓泄漏）。
失败语义：连不上/握手失败 → 抛 `McpConnectionError`（结构化、绝不半初始化后静默返回）。
分层：只在 `capabilities/mcp` 内 import SDK；kernel 不持 SDK 句柄（HARD C1/C14；工具经注册表挂进）。
"""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import AsyncExitStack
from typing import Any, TextIO

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_log = logging.getLogger("questor.mcp")


class McpConnectionError(RuntimeError):
    """transport/session 启动或使用失败（连不上 / 握手失败 / 未连接即调用）。"""


class McpConnection:
    """拥有单个 stdio MCP server 的 transport + session 生命周期。"""

    def __init__(self, params: StdioServerParameters, *, errlog: TextIO | None = None, handshake_timeout_s: float = 30.0) -> None:
        self._params = params
        # 子进程 stderr 落点（D-16.4-A）：默认继承 sys.stderr；生产传每-run 独立文件句柄。
        self._errlog: TextIO = errlog if errlog is not None else sys.stderr
        self._handshake_timeout_s = handshake_timeout_s
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    @property
    def connected(self) -> bool:
        return self._session is not None

    async def start(self) -> None:
        """起子进程 + 建 session + 握手。已连接则空操作；失败清理已获取的资源后再抛（不留半初始化）。"""
        if self._session is not None:
            return
        stack = AsyncExitStack()
        try:
            read_stream, write_stream = await stack.enter_async_context(stdio_client(self._params, errlog=self._errlog))
            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            # 握手限时：活而不回 initialize 的 server 不能把 loop 挂死（C13）；超时走下面 except 清理。
            await asyncio.wait_for(session.initialize(), timeout=self._handshake_timeout_s)
        except Exception as exc:  # noqa: BLE001 - 统一归一成连接失败；先撤销栈再抛，绝不泄漏 transport/进程
            await stack.aclose()
            raise McpConnectionError(f"failed to connect MCP server {self._params.command!r}: {exc}") from exc
        self._stack = stack
        self._session = session

    def _require_session(self) -> ClientSession:
        if self._session is None:
            raise McpConnectionError("MCP connection is not started")
        return self._session

    async def list_tools(self) -> list[Any]:
        """返回远程工具定义列表（SDK Tool 对象：含 name/description/inputSchema）。"""
        result = await self._require_session().list_tools()
        return list(result.tools)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """调用远程工具，返回 SDK CallToolResult。断开/异常由 SDK 抛出，交上层 `_execute_tool` 归一闭合（C19）。"""
        return await self._require_session().call_tool(name, arguments)

    async def aclose(self) -> None:
        """退出资源栈：关 session + transport，并由 SDK 终止子进程树。幂等。"""
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._session = None
