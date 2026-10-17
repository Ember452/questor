"""跨进程关联 canary（C16；DoD⑤）。

真子进程 roundtrip：给定 `run_id`，MCP server 的 stderr 落到**独立文件**
`mcp-stderr-<run_id>.log`，文件名/首行都带同 `run_id`——证明"关联只能显式注入"这条真兑现
（不是"代码里写了注入"的完成感）。断言真子进程 banner 落到该文件、而非污染 stdout/主干。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from mcp import StdioServerParameters

from questor.capabilities.mcp.connection import McpConnection
from questor.providers.mcp_stderr import open_mcp_stderr_log

SERVER = Path(__file__).resolve().parents[1] / "support" / "mcp_demo_server.py"


@pytest.mark.asyncio
async def test_child_stderr_lands_in_per_run_file_locatable_by_run_id(tmp_path: Path) -> None:
    run_id = "run-canary-1"
    log_dir = tmp_path / "mcp"
    handle = open_mcp_stderr_log(log_dir, run_id)
    conn = McpConnection(StdioServerParameters(command=sys.executable, args=[str(SERVER)]), errlog=handle)
    try:
        await conn.start()
        await conn.call_tool("echo", {"text": "x"})
        await conn.aclose()
    finally:
        handle.flush()
        handle.close()

    log_file = log_dir / f"mcp-stderr-{run_id}.log"
    assert log_file.exists()  # 主关联：文件名带 run_id
    text = log_file.read_text(encoding="utf-8")
    assert f"run_id={run_id}" in text  # 辅关联：首行标记
    assert "demo mcp server starting" in text  # 真子进程 stderr 确实落到本 run 文件（C20 独立通道）
