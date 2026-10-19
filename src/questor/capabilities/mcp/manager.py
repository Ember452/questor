"""L3 MCP server 编排（C23/T2-T3；`docs/plan/05` Group 5）。

对每个 server：spawn 侧安全门（双门第二道）→ 连接 → `list_tools` → 产 `McpRemoteTool`；
连接失败/命中安全门 → WARNING 出声并跳过该 server、保留其余（C6，仿 skills 隔离）。`aclose` 回收全部子进程。

分层：env 擦除（C17）与 per-run stderr 打开（C14/C15）由 **L6 组合根以工厂注入**——
`capabilities` 绝不 import `providers`（HARD C1/C14，`check_layering_ast` FORBIDDEN）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any, TextIO

from mcp import StdioServerParameters

from questor.capabilities.mcp.config import McpServerConfig
from questor.capabilities.mcp.connection import McpConnection, McpConnectionError
from questor.capabilities.mcp.remote_tool import McpRemoteTool
from questor.capabilities.mcp.security import McpSecurityError, validate_server_entry

_log = logging.getLogger("questor.mcp")

#: 单个 server 的发现上限（C18 有界 / 防远程 server 一次性报海量工具撑爆 prompt 与工具面；
#: 超限只接前 N 个并出声）。
MAX_DISCOVERED_TOOLS = 256


def _build_tools(conn: McpConnection, server_name: str, raw_tools: list[Any], *, limit: int = MAX_DISCOVERED_TOOLS) -> list[McpRemoteTool]:
    """把发现到的远程 tool 定义映射成 `McpRemoteTool`：先按上限截断、再逐个容错。

    单个畸形 descriptor（`McpRemoteTool` 构造抛错）只跳过该工具并出声，不拖垮整 server
    的发现（C6/C18，DoD③ 不崩宿主）。超限截断也出声。
    """
    tools: list[McpRemoteTool] = []
    if len(raw_tools) > limit:
        _log.warning("MCP server '%s' advertised %d tools; capping at %d (C18 bounded)", server_name, len(raw_tools), limit)
        raw_tools = raw_tools[:limit]
    for tool_def in raw_tools:
        try:
            tools.append(
                McpRemoteTool(
                    connection=conn,
                    server_name=server_name,
                    raw_name=str(tool_def.name),
                    description=str(getattr(tool_def, "description", "") or ""),
                    input_schema=getattr(tool_def, "inputSchema", None),
                )
            )
        except Exception as exc:  # noqa: BLE001 - 单个远程工具描述畸形不得拖垮整批发现（C6）
            _log.warning("skipping malformed remote tool on server '%s' (name=%r): %s", server_name, getattr(tool_def, "name", "?"), exc)
    return tools


class McpManager:
    """拥有到若干 stdio MCP server 的连接，并把远程工具适配成本地 `Tool`。"""

    def __init__(
        self,
        *,
        make_stdio_params: Callable[[McpServerConfig], StdioServerParameters],
        make_errlog: Callable[[McpServerConfig], TextIO],
    ) -> None:
        self._make_params = make_stdio_params
        self._make_errlog = make_errlog
        self._connections: list[McpConnection] = []

    async def discover(self, configs: Sequence[McpServerConfig]) -> list[McpRemoteTool]:
        """逐个连接并发现远程工具；不可用的 server 出声跳过、不影响其余。"""
        tools: list[McpRemoteTool] = []
        for cfg in configs:
            try:
                validate_server_entry(cfg)  # spawn 侧第二道安全门（载入侧由组合根再跑一次）
            except McpSecurityError as exc:
                _log.warning("skipping MCP server '%s' at spawn gate: %s", cfg.name, exc)
                continue
            try:
                conn = McpConnection(self._make_params(cfg), errlog=self._make_errlog(cfg))
                await conn.start()
            except McpConnectionError as exc:
                _log.warning("MCP server '%s' failed to connect: %s", cfg.name, exc)
                continue
            self._connections.append(conn)
            try:
                raw_tools: list[Any] = await conn.list_tools()
            except Exception as exc:  # noqa: BLE001 - 单 server 发现失败出声、不拖垮其余（C6）
                _log.warning("MCP server '%s' tool discovery failed: %s", cfg.name, exc)
                continue
            tools.extend(_build_tools(conn, cfg.name, raw_tools))
        return tools

    async def aclose(self) -> None:
        """关闭全部连接（SDK 负责终止子进程树），幂等。"""
        for conn in self._connections:
            await conn.aclose()
        self._connections.clear()
