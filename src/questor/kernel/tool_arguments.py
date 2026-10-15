"""L2 arg-key 抽取器（design/03 §11；T5）。

纯函数、无 IO、无权限判断。它只把工具参数转换成可审计的路径/shell/action 事实；
真实安全分类由 shell parser、permission policy 和 capability floor 完成。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from questor.contracts.tool_args import ACTION_ARG_KEYS, PATCH_PATH_PREFIXES, PATH_ARG_KEYS, SHELL_ARG_KEYS


def _strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, (list, tuple)):
        return tuple(item for item in value if isinstance(item, str) and item.strip())
    return ()


def _dedupe(items: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return tuple(result)


def extract_paths(arguments: Mapping[str, object] | None) -> tuple[str, ...]:
    """从 path keys 和 apply_patch headers 抽取路径候选，保持首次出现顺序。"""
    if not arguments:
        return ()
    found: list[str] = []
    for key in PATH_ARG_KEYS:
        found.extend(_strings(arguments.get(key)))
    patch = arguments.get("patch")
    if isinstance(patch, str):
        for line in patch.splitlines():
            for prefix in PATCH_PATH_PREFIXES:
                if line.startswith(prefix):
                    candidate = line.removeprefix(prefix).strip()
                    if candidate:
                        found.append(candidate)
                    break
    return _dedupe(tuple(found))


def extract_shell_commands(arguments: Mapping[str, object] | None) -> tuple[str, ...]:
    """抽取 shell command/commands/script；不在此处执行任何 shell 解析。"""
    if not arguments:
        return ()
    found: list[str] = []
    for key in SHELL_ARG_KEYS:
        found.extend(_strings(arguments.get(key)))
    return _dedupe(tuple(found))


def extract_actions(arguments: Mapping[str, object] | None) -> tuple[str, ...]:
    """抽取动作型参数，供未来 browser/scheduler/env 等 capability 复用。"""
    if not arguments:
        return ()
    found: list[str] = []
    for key in ACTION_ARG_KEYS:
        found.extend(_strings(arguments.get(key)))
    return _dedupe(tuple(found))


__all__ = ["extract_actions", "extract_paths", "extract_shell_commands"]
