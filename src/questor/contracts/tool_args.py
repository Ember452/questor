"""L0 arg-key 词典（design/03 §11 步骤③）。

本模块**只放数据**，不 import state/kernel/providers/capabilities，也不放抽取逻辑：
路径、shell、动作与 patch header 是跨层共享的“词汇”，抽取函数留在 L2。
"""

from __future__ import annotations

#: 明确表达“这是路径”的常见工具参数键。工具名不能替代这个事实。
PATH_ARG_KEYS: tuple[str, ...] = (
    "file_path",
    "paths",
    "path",
    "filename",
    "target",
    "workspace_path",
    "root",
    "destination",
    "source",
)

#: 明确表达“这是 shell 输入”的键。值是 command/script 而非路径，需由 dialect parser 处理。
SHELL_ARG_KEYS: tuple[str, ...] = (
    "command",
    "commands",
    "script",
)

#: 动作型副作用键（browser/scheduler/env/config 等未来 capability 共用）。
ACTION_ARG_KEYS: tuple[str, ...] = ("action",)

#: apply_patch envelope 的路径 header；必须逐行抽取，不能把整段 patch 当一个路径。
PATCH_PATH_PREFIXES: tuple[str, ...] = (
    "*** Add File: ",
    "*** Update File: ",
    "*** Delete File: ",
    "*** Move to: ",
)

#: redirect 的合法丢弃目标；它们不是 workspace/凭据路径。
NULL_SINKS: frozenset[str] = frozenset(
    {
        "/dev/null",
        "/dev/stdout",
        "/dev/stderr",
        "/dev/tty",
        "/dev/fd/1",
        "/dev/fd/2",
        "nul",
        "NUL",
        "con",
        "CON",
    }
)

#: workspace root 内仍须额外保护的 agent/config/credential 文件；不能用普通 rules 放宽。
PROTECTED_IN_ROOTS: frozenset[str] = frozenset(
    {
        "mcp.json",
        "permissions.json",
        "config.json",
        ".env",
        ".env.*",
    }
)


__all__ = [
    "ACTION_ARG_KEYS",
    "NULL_SINKS",
    "PATCH_PATH_PREFIXES",
    "PATH_ARG_KEYS",
    "PROTECTED_IN_ROOTS",
    "SHELL_ARG_KEYS",
]
