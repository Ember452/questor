"""P5 对抗式验收审计后的加固测试（cap/守卫/schema 深度/占位符/env-repr/suffix）。

每条对应审计里"我认"的项：
- 发现上限 256（C18）+ 单个畸形远程 descriptor 不得崩发现（DoD③）；
- 深嵌套远程 schema 不得 RecursionError；
- `${VAR}` 未展开 fail-closed 跳过；
- `McpServerConfig.env` 值不得进 repr（C17/C20）；
- 远程工具名可按 `mcp_<server>_*` suffix 匹配（C9 权限）。
"""

from __future__ import annotations

import fnmatch
import json
import logging
from pathlib import Path

import pytest

from questor.capabilities.mcp.config import McpServerConfig, load_server_configs
from questor.capabilities.mcp.manager import MAX_DISCOVERED_TOOLS, _build_tools
from questor.capabilities.mcp.naming import remote_tool_name
from questor.capabilities.mcp.schema import normalize_mcp_schema


class _Def:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = "d"
        self.inputSchema = {"type": "object", "properties": {}}


def test_build_tools_caps_at_limit_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    defs = [_Def(f"t{i}") for i in range(MAX_DISCOVERED_TOOLS + 50)]
    with caplog.at_level(logging.WARNING, logger="questor.mcp"):
        tools = _build_tools(conn=object(), server_name="big", raw_tools=defs)
    assert len(tools) == MAX_DISCOVERED_TOOLS
    assert any("capping" in r.getMessage() for r in caplog.records if r.name == "questor.mcp")


def test_build_tools_skips_malformed_descriptor_without_crashing(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="questor.mcp"):
        # raw_tools 里混一个 None（无 .name）→ 构造抛错，应被逐个守卫吞掉并出声，保留其余。
        tools = _build_tools(conn=object(), server_name="s", raw_tools=[_Def("good"), None])  # type: ignore[list-item]
    assert [t.spec.name for t in tools] == ["mcp_s_good"]
    assert any("malformed" in r.getMessage() for r in caplog.records if r.name == "questor.mcp")


def test_normalize_schema_survives_deep_nesting() -> None:
    schema: dict = {"type": "string"}
    for _ in range(200):  # 远超 _MAX_SCHEMA_DEPTH
        schema = {"type": "object", "properties": {"n": schema}}
    result = normalize_mcp_schema(schema)  # 不得 RecursionError
    assert isinstance(result, dict)


def test_unresolved_placeholder_server_is_skipped(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps({"mcpServers": {"x": {"command": "run", "args": ["--key=${SECRET}"]}}}),
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING, logger="questor.mcp"):
        configs = load_server_configs(path)
    assert configs == []  # fail-closed：不把未展开占位符当命令启动
    assert any("placeholder" in r.getMessage() for r in caplog.records if r.name == "questor.mcp")


def test_config_repr_hides_env_values() -> None:
    cfg = McpServerConfig(name="s", command="c", args=(), env={"API_KEY": "super-secret-value"})
    assert "super-secret-value" not in repr(cfg)


def test_remote_tool_name_matches_server_suffix_pattern() -> None:
    # 权限规则按 suffix 匹配（C9）：`mcp_fetch_*` 必须命中远程工具名。
    assert fnmatch.fnmatch(remote_tool_name("fetch", "get_page"), "mcp_fetch_*")
