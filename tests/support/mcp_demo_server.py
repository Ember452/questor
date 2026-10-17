"""Test-only stdio MCP server (FastMCP) for real roundtrip tests — NOT production code.

由连接测试用 `sys.executable` 起成**真子进程**（DoD②：真 stdio 假 server，不用 fake 对象冒充真进程）。
提供 `echo`/`boom` 两个工具 + 启动时向 stderr 打一行 banner（供 C14/C16 子进程 stderr 观测测试）。
"""

from __future__ import annotations

import sys

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("demo")


@mcp.tool()
async def echo(text: str) -> str:
    """Return the input text unchanged."""
    return text


@mcp.tool()
async def boom() -> str:
    """Always raises, to exercise error mapping from a remote tool."""
    raise RuntimeError("boom from remote server")


@mcp.tool()
async def hang() -> str:
    """Sleep far longer than any test deadline, to exercise mid-call cancellation + session reuse."""
    import anyio

    await anyio.sleep(30)
    return "should not finish"


if __name__ == "__main__":
    # 启动 banner 走 stderr：验证它落到我们指定的独立文件、不污染 stdout 的 JSON-RPC 通道。
    print("demo mcp server starting", file=sys.stderr, flush=True)
    mcp.run(transport="stdio")
