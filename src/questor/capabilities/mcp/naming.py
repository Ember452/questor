"""L3 远程工具命名（C20；`docs/plan/05` T3，`capabilities/mcp/README.md` 约定）。

命名 `mcp_<server>_<tool>`（本仓约定，单下划线 + suffix 权限匹配；有意区别于 DeepCode 的
`mcp__`）。每段清洗成 provider 安全字符集 [A-Za-z0-9_-]，空段退化 "unnamed"。名字含服务器段，
天然不与内置裸名相同（防远程伪装成 `read` 等），真冲突由注册表守卫（C21）兜。只依赖 stdlib。"""

from __future__ import annotations

import re

_INVALID = re.compile(r"[^A-Za-z0-9_-]+")


def _segment(value: str) -> str:
    cleaned = _INVALID.sub("_", value).strip("_")
    return cleaned or "unnamed"


def remote_tool_name(server: str, raw_tool: str) -> str:
    """把 (server, 远程裸工具名) 拼成模型可见的 `mcp_<server>_<tool>`。"""
    return f"mcp_{_segment(server)}_{_segment(raw_tool)}"
