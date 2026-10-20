"""L3 工具集=数据（OPT-5；v3 §21 G1）。

本轮只把「默认 11 工具 + 顺序」从 surface 的硬编码元组搬到**数据表**：

- ``TOOL_FACTORIES``：tool_id → 无参工厂；工厂只构造工具对象，不做权限/沙箱判定。
- ``PROFILES``：profile → 有序 tool_id；顺序参与 provider 工具面字节形态，**不得随意改**。
- ``build_tools(profile)``：组合根/surface 的唯一取件口；未知 profile 回落 ``default`` 并出声
  （工具面缺失比"少一个工具"更伤，故 fail-open 到默认名册；这不是权限放宽）。

落点归组合根消费（`AssembleSpec.profile` / `CliSurface`），surface 不再各写一份元组。
``capabilities`` 层只 import contracts + 同层工具模块，不 import kernel/state/providers。
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from questor.capabilities.subagent.delegate import DelegateTool
from questor.capabilities.tools.apply_patch import ApplyPatchTool
from questor.capabilities.tools.bash import BashTool
from questor.capabilities.tools.edit import EditTool
from questor.capabilities.tools.glob import GlobTool
from questor.capabilities.tools.grep import GrepTool
from questor.capabilities.tools.ls import LsTool
from questor.capabilities.tools.memory_search import MemorySearchTool
from questor.capabilities.tools.powershell import PowerShellTool
from questor.capabilities.tools.read import ReadTool
from questor.capabilities.tools.write import WriteTool
from questor.contracts.tool import Tool

_log = logging.getLogger("questor.toolset")

#: tool_id → 无参工厂。tool_id 是稳定数据键（不是类名），换实现不动 profile。
TOOL_FACTORIES: dict[str, Callable[[], Tool]] = {
    "read": ReadTool,
    "write": WriteTool,
    "edit": EditTool,
    "apply_patch": ApplyPatchTool,
    "ls": LsTool,
    "glob": GlobTool,
    "grep": GrepTool,
    "bash": BashTool,
    "powershell": PowerShellTool,
    "memory_search": MemorySearchTool,
    "delegate": DelegateTool,
}

#: 默认 profile 名（生产入口未给 profile 时用它）。
DEFAULT_PROFILE = "default"

#: profile → 有序 tool_id；默认 11 个的顺序与 OPT-5 前的硬编码元组逐项相同。
PROFILES: dict[str, tuple[str, ...]] = {
    DEFAULT_PROFILE: (
        "read",
        "write",
        "edit",
        "apply_patch",
        "ls",
        "glob",
        "grep",
        "bash",
        "powershell",
        "memory_search",
        "delegate",
    ),
}


def tool_ids(profile: str | None = None) -> tuple[str, ...]:
    """profile 的 tool_id 序列；未知 profile 回落默认名册并 WARN（不静默变空）。"""
    name = profile or DEFAULT_PROFILE
    ids = PROFILES.get(name)
    if ids is None:
        _log.warning("unknown tool profile %r; falling back to %r", name, DEFAULT_PROFILE)
        ids = PROFILES[DEFAULT_PROFILE]
    return ids


def build_tools(profile: str | None = None) -> tuple[Tool, ...]:
    """按 profile 构造工具元组（顺序即 provider 工具面顺序）。"""
    return tuple(TOOL_FACTORIES[tool_id]() for tool_id in tool_ids(profile))


__all__ = ["DEFAULT_PROFILE", "PROFILES", "TOOL_FACTORIES", "build_tools", "tool_ids"]
