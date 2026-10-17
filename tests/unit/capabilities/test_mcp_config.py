"""MCP server 配置载入的判红用例（C09；`docs/plan/05` T1）。

shape = Claude/生态标准 ``{"mcpServers": {name: {command, args, env}}}``（对齐 PROTECTED_IN_ROOTS
的 ``mcp.json``）。env 值属机密，只留在 config 对象供子进程透传，绝不入事件/日志（C17/C20）。
单条坏 entry → 出声跳过、保留其余（C6，仿 skills 隔离）；整个文件 JSON 坏 → fail-closed 抛。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from questor.capabilities.mcp.config import McpConfigError, load_server_configs


def _write(path: Path, obj: object) -> Path:
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


def test_parses_valid_servers_and_preserves_env(tmp_path: Path) -> None:
    cfg = _write(
        tmp_path / "mcp.json",
        {
            "mcpServers": {
                "fetch": {"command": "uvx", "args": ["mcp-server-fetch"], "env": {"API_KEY": "secret"}},
                "files": {"command": "node", "args": ["server.js"]},
            }
        },
    )
    servers = load_server_configs(cfg)
    by_name = {s.name: s for s in servers}
    assert set(by_name) == {"fetch", "files"}
    assert by_name["fetch"].command == "uvx"
    assert by_name["fetch"].args == ("mcp-server-fetch",)
    assert by_name["fetch"].env["API_KEY"] == "secret"
    assert by_name["files"].args == ("server.js",)


def test_missing_file_yields_no_servers(tmp_path: Path) -> None:
    assert load_server_configs(tmp_path / "absent.json") == []


def test_invalid_json_raises_fail_closed(tmp_path: Path) -> None:
    bad = tmp_path / "mcp.json"
    bad.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(McpConfigError):
        load_server_configs(bad)


def test_bad_entry_is_skipped_with_warning_good_kept(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    cfg = _write(
        tmp_path / "mcp.json",
        {"mcpServers": {"ok": {"command": "uvx"}, "no_cmd": {"args": ["x"]}, "Bad Name": {"command": "y"}}},
    )
    with caplog.at_level(logging.WARNING, logger="questor.mcp"):
        servers = load_server_configs(cfg)
    assert {s.name for s in servers} == {"ok"}  # 缺 command / 非法 name 都跳过
    warns = [r.getMessage() for r in caplog.records if r.name == "questor.mcp"]
    assert any("no_cmd" in m for m in warns)  # 坏 entry 一定出声（C6）
