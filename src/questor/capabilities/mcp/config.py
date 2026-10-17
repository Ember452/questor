"""L3 MCP server 配置载入（C09；`docs/plan/05` T1）。

shape = 生态标准 ``{"mcpServers": {name: {command, args, env}}}``（落点为 workspace root 的
``mcp.json``，已在 `contracts/tool_args.PROTECTED_IN_ROOTS` 写保护内——agent 不得自改自身 MCP 面）。
失败语义（C6/C17）：
- 文件不存在 → 返回 ``[]``（无 MCP 配置是合法的）；
- 文件存在但 JSON/顶层形状坏 → 抛 `McpConfigError`（fail-closed，绝不假装"没有 server"静默继续）；
- 单条 entry 非法（缺 command / 非法 name）→ WARNING 出声并跳过该条、保留其余（仿 skills 隔离）。
``env`` 值属机密，只留在 config 对象里供子进程透传，**绝不进事件/日志**（C17/C20）。只依赖 stdlib。"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

_log = logging.getLogger("questor.mcp")

#: server 名字符集（用于命名规则 `mcp_<server>_<tool>`，避免非法字符进工具名）。
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

#: 未展开的 `${VAR}` 占位符（fail-closed 拒载，不把模板字面量递给子进程）。
_PLACEHOLDER_RE = re.compile(r"\$\{[^}]*\}")

#: MCP 配置文件名。落点在 workspace root，必须与 `contracts/tool_args.PROTECTED_IN_ROOTS` 里的
#: token 一致（C10 测试机器守这层耦合）——agent 不得自改自身 MCP 面。
MCP_CONFIG_FILENAME = "mcp.json"


class McpConfigError(ValueError):
    """mcp.json 整体不可解析/形状非法（fail-closed，与"无配置"区分开）。"""


@dataclass(frozen=True, slots=True)
class McpServerConfig:
    """一个 stdio MCP server 的配置。``env`` 只读、只用于子进程透传。"""

    name: str
    command: str
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # 归一为不可变视图（frozen dataclass 的浅冻结挡不住内层 dict 被改）。
        object.__setattr__(self, "args", tuple(self.args))
        object.__setattr__(self, "env", MappingProxyType(dict(self.env)))

    def __repr__(self) -> str:
        # env 值属机密（C17/C20）：repr 只露键名不露值，防止 config 被意外进日志/repr 泄密。
        return f"McpServerConfig(name={self.name!r}, command={self.command!r}, args={self.args!r}, env=<redacted:{len(self.env)} keys>)"


def _build_entry(name: str, entry: object) -> McpServerConfig | None:
    """把一条 entry 归一成 config；非法则返回 None（调用方已负责出声跳过）。"""
    if not _NAME_RE.match(name):
        _log.warning("skipping MCP server with invalid name %r", name)
        return None
    if not isinstance(entry, dict):
        _log.warning("skipping MCP server '%s': entry is not an object", name)
        return None
    command = entry.get("command")
    if not isinstance(command, str) or not command.strip():
        _log.warning("skipping MCP server '%s': missing or empty 'command'", name)
        return None
    raw_args = entry.get("args", [])
    if not isinstance(raw_args, list) or not all(isinstance(a, str) for a in raw_args):
        _log.warning("skipping MCP server '%s': 'args' must be a list of strings", name)
        return None
    raw_env = entry.get("env", {})
    if not isinstance(raw_env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in raw_env.items()):
        _log.warning("skipping MCP server '%s': 'env' must be a string->string object", name)
        return None
    # 未展开的 ${VAR} 占位符：fail-closed 跳过该 server（不把模板字面量当命令/参数启动）。
    if (
        _PLACEHOLDER_RE.search(command)
        or any(_PLACEHOLDER_RE.search(a) for a in raw_args)
        or any(_PLACEHOLDER_RE.search(k) or _PLACEHOLDER_RE.search(v) for k, v in raw_env.items())
    ):
        _log.warning("skipping MCP server '%s': unresolved ${VAR} placeholder in command/args/env", name)
        return None
    return McpServerConfig(name=name, command=command, args=tuple(raw_args), env=MappingProxyType(dict(raw_env)))


def load_server_configs(mcp_json: Path) -> list[McpServerConfig]:
    """从 ``mcp.json`` 载入 server 配置列表（详见模块 docstring 的失败语义）。"""
    if not mcp_json.exists():
        return []
    try:
        data = json.loads(mcp_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise McpConfigError(f"cannot parse mcp.json at {mcp_json}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("mcpServers"), dict):
        raise McpConfigError(f"mcp.json at {mcp_json} must be an object with a 'mcpServers' object")

    servers: list[McpServerConfig] = []
    for name, entry in data["mcpServers"].items():
        config = _build_entry(str(name), entry)
        if config is not None:
            servers.append(config)
    return servers
