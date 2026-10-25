"""CLI 工具白/黑名单 → 运行时设置。

`--allowed-tools` 的语义是**严格白名单**（只允许列出的工具），与
`settings.allowed_tools` 的“显式放行”不同；这里把它翻译成
“allowed + 其余全部 denied”，从而复用既有的 policy 语义，不新增分支。
"""

from __future__ import annotations

from collections.abc import Iterable

from questorharness.capabilities.tools.registry import create_default_tool_registry


class ToolPolicyError(ValueError):
    """工具名不存在 / 白黑名单冲突。"""


def _tokens(values: Iterable[str] | None) -> list[str]:
    """把 `a,b c` 这类输入拆成去重的名字列表（保序）。"""
    tokens: list[str] = []
    for value in values or ():
        for token in str(value).replace(",", " ").split():
            if token and token not in tokens:
                tokens.append(token)
    return tokens


def registry_tool_names() -> frozenset[str]:
    """注册表内真实存在的工具名。"""
    return frozenset(tool.name for tool in create_default_tool_registry().list_tools())


def resolve_tool_policy(
    allowed_tools: Iterable[str] | None,
    disallowed_tools: Iterable[str] | None,
    *,
    known_names: frozenset[str] | None = None,
) -> tuple[list[str] | None, list[str] | None]:
    """返回 (allowed, denied)；两者皆为 None 表示完全继承。

    规则：
    - 未声明任何名单 → (None, None)；
    - `*` 视为“全部” → allowed=None；
    - 声明了 allowed → 严格白名单，denied 补上“其余全部”；
    - 未知工具名 → ToolPolicyError（fail-closed，不静默忽略）。
    """
    allowed = _tokens(allowed_tools)
    denied = _tokens(disallowed_tools)
    if not allowed and not denied:
        return None, None
    known = known_names if known_names is not None else registry_tool_names()
    unknown = sorted((set(allowed) | set(denied)) - known - {"*"})
    if unknown:
        raise ToolPolicyError(
            "unknown tool name(s): " + ", ".join(unknown) + "; run `questor --help` for the list"
        )
    denied_set = set(denied)
    if not allowed or "*" in allowed:
        return None, sorted(denied_set) or None
    overlap = sorted(set(allowed) & denied_set)
    if overlap:
        raise ToolPolicyError("tool(s) both allowed and denied: " + ", ".join(overlap))
    strict_denied = sorted(denied_set | (known - set(allowed)))
    return sorted(set(allowed)), strict_denied
