"""L2 arg-key 抽取器（design/03 §3 第③层；T5）。

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


def _looks_like_unified_diff(text: str) -> bool:
    """含 ``--- `` 与 ``+++ `` 头且带 ``@@`` 段才当 unified diff，避免把普通文本误当补丁。"""
    has_header = any(ln.startswith("--- ") for ln in text.splitlines()) and any(
        ln.startswith("+++ ") for ln in text.splitlines()
    )
    return has_header and any(ln.startswith("@@") for ln in text.splitlines())


def _diff_header_path(raw: str) -> tuple[str, ...]:
    """从一个 ``--- ``/``+++ `` 头取候选路径：``/dev/null`` 无路径；同时给原始与去 ``a/``/``b/`` 两个形态。

    两个形态都作候选（宁多勿漏）：工具自身按去前缀形态写文件，而 ``PROTECTED_IN_ROOTS`` 检查需看到
    裸名（如 ``.env``）才能拦住；原始形态兼顾真实目录名不被误剥的情形。"""
    value = raw.strip()
    if value == "/dev/null" or not value:
        return ()
    out = [value]
    if len(value) > 2 and value[1] == "/" and value[0] in "ab":
        out.append(value[2:])
    return tuple(out)


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
    # unified diff（apply_patch 的 ``input``/``patch``）：从 ``--- ``/``+++ `` 头抽路径（#156 BLK-1）。
    for key in ("patch", "input"):
        value = arguments.get(key)
        if isinstance(value, str) and _looks_like_unified_diff(value):
            for line in value.splitlines():
                if line.startswith("--- "):
                    found.extend(_diff_header_path(line[4:]))
                elif line.startswith("+++ "):
                    found.extend(_diff_header_path(line[4:]))
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
