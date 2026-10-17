"""L6 MCP bootstrap 的判红用例（Group 5 / C17 / DoD②⑤；真子进程）。

`discover_mcp_tools` 把 mcp.json 接成真连接 → 发现远程工具 → per-run stderr 文件；teardown 回收。
C17：server.env 里出现 provider 凭据名（如 OPENAI_API_KEY）→ 拒绝起该 server、出声、不外泄我方凭据。
用 `sys.executable` 起真 demo server（非 mock）。"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

from questor.surfaces.mcp_bootstrap import discover_mcp_tools

SERVER = Path(__file__).resolve().parents[1] / "support" / "mcp_demo_server.py"


def _write_mcp_json(root: Path, servers: dict) -> Path:
    path = root / "mcp.json"
    path.write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")
    return path


@pytest.mark.asyncio
async def test_discover_tools_and_per_run_stderr_and_teardown(tmp_path: Path) -> None:
    mcp_json = _write_mcp_json(tmp_path, {"demo": {"command": sys.executable, "args": [str(SERVER)]}})
    log_dir = tmp_path / "logs"
    tools, teardown = await discover_mcp_tools(mcp_json=mcp_json, log_dir=log_dir, run_id="run-b1")
    try:
        names = {t.spec.name for t in tools}
        assert "mcp_demo_echo" in names
    finally:
        await teardown()
    stderr_file = log_dir / "mcp" / "mcp-stderr-run-b1-demo.log"
    assert stderr_file.exists()  # per-run + per-server 独立 stderr 文件，文件名带 run_id
    assert "run-b1" in stderr_file.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_no_mcp_json_yields_no_tools(tmp_path: Path) -> None:
    tools, teardown = await discover_mcp_tools(mcp_json=tmp_path / "absent.json", log_dir=tmp_path, run_id="r")
    assert tools == []
    await teardown()  # noop，不抛


@pytest.mark.asyncio
async def test_provider_credential_env_is_refused(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    mcp_json = _write_mcp_json(
        tmp_path,
        {"greedy": {"command": sys.executable, "args": [str(SERVER)], "env": {"OPENAI_API_KEY": "sk-leak"}}},
    )
    with caplog.at_level(logging.WARNING, logger="questor.mcp"):
        tools, teardown = await discover_mcp_tools(mcp_json=mcp_json, log_dir=tmp_path, run_id="r2")
    try:
        assert tools == []  # 该 server 被拒，绝不带我们的 provider 凭据启动（C17）
    finally:
        await teardown()
    warns = [r.getMessage() for r in caplog.records if r.name == "questor.mcp"]
    assert any("OPENAI_API_KEY" in m for m in warns)
