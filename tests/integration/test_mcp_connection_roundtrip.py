"""MCP 连接真 stdio roundtrip + 失败恢复的判红用例（C12/C13；DoD②/③）。

用 `sys.executable` 起**真 FastMCP 子进程**（不用 fake 对象冒充真进程），跑
`discover → initialize → tools/list → call → teardown`。断言 aclose 后子进程被回收
（否则本仓非守护线程/进程泄漏守卫判红）。失败路径：命令不存在 → 快速抛 `McpConnectionError`、
不留半初始化连接、不挂死。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from mcp import StdioServerParameters

from questor.capabilities.mcp.connection import McpConnection, McpConnectionError

SERVER = Path(__file__).resolve().parents[1] / "support" / "mcp_demo_server.py"


def _result_text(result) -> str:
    parts = [block.text for block in result.content if getattr(block, "text", None)]
    return "\n".join(p for p in parts if p)


@pytest.mark.asyncio
async def test_roundtrip_discover_and_call() -> None:
    conn = McpConnection(StdioServerParameters(command=sys.executable, args=[str(SERVER)]))
    await conn.start()
    try:
        assert conn.connected
        names = {t.name for t in await conn.list_tools()}
        assert "echo" in names and "boom" in names
        result = await conn.call_tool("echo", {"text": "hi"})
        assert _result_text(result) == "hi"
    finally:
        await conn.aclose()
    assert not conn.connected


@pytest.mark.asyncio
async def test_remote_tool_error_surfaces_as_error_result() -> None:
    """远程工具抛错：SDK 返回 isError 的结果（不是 Python 异常）——验证它被识别为错误而非静默成功。"""
    conn = McpConnection(StdioServerParameters(command=sys.executable, args=[str(SERVER)]))
    await conn.start()
    try:
        result = await conn.call_tool("boom", {})
        assert result.isError is True
    finally:
        await conn.aclose()


@pytest.mark.asyncio
async def test_unreachable_command_fails_fast_no_leak() -> None:
    conn = McpConnection(StdioServerParameters(command="__no_such_mcp_server_bin__", args=[]))
    with pytest.raises(McpConnectionError):
        await conn.start()
    assert not conn.connected  # 失败不留半初始化


@pytest.mark.asyncio
async def test_silent_server_handshake_times_out() -> None:
    """活而不回 initialize 的真子进程：限时内抛错、不挂死、aclose 回收（C13）。"""
    conn = McpConnection(
        StdioServerParameters(command=sys.executable, args=["-c", "import time; time.sleep(30)"]),
        handshake_timeout_s=1.0,
    )
    with pytest.raises(McpConnectionError):
        await conn.start()
    assert not conn.connected
