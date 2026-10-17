"""MCP 在途调用被取消后，session 仍可服务下一次调用（审计 §6 关注的加固回归测试；真子进程）。

风险来源：`_execute_tool` 用 `asyncio.wait_for` 给工具调用套 deadline；若一次 MCP 远程调用挂死被
中途取消，官方 `mcp` SDK 的会话会不会残留未决请求、导致下一次调用卡死/错乱？本测试用真 FastMCP
子进程直接验：取消一个 `hang`（睡 30s）调用后，紧接着的 `echo` 调用必须正常返回。若 SDK 会话在取消
后失能，本测试会超时判红 → 那将要求在 `McpConnection` 加"调用超时即标不健康/重建"的兜底。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from mcp import StdioServerParameters

from questor.capabilities.mcp.connection import McpConnection

SERVER = Path(__file__).resolve().parents[1] / "support" / "mcp_demo_server.py"


def _text(result) -> str:
    return "".join(b.text for b in result.content if getattr(b, "text", None))


@pytest.mark.asyncio
async def test_session_survives_cancelled_call_and_serves_next() -> None:
    conn = McpConnection(StdioServerParameters(command=sys.executable, args=[str(SERVER)]), errlog=sys.stderr)
    await conn.start()
    try:
        # 1) 一次远程调用挂死，被 Harness 式 deadline 中途取消。
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(conn.call_tool("hang", {}), timeout=0.5)
        # 2) 取消之后，同一 session 必须仍能正常服务下一次调用（否则本行会挂到测试超时）。
        result = await asyncio.wait_for(conn.call_tool("echo", {"text": "ping"}), timeout=15)
        assert "ping" in _text(result)
    finally:
        await conn.aclose()
