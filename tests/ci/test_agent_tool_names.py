"""Agent 定义里的工具名必须存在于工具注册表。

声明了不存在的名字 = 静默失效：`disallowed_tools=["file_write"]` 不会拦住
`write_file`，`tools=["Edit"]` 也不会放行 `edit_file`。这条守卫把“名字”
本身当作契约，任何新增/改名都必须两边同时改。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from questorharness.capabilities.tools.registry import create_default_tool_registry
from questorharness.runtime.coordinator.agent_definitions import get_builtin_agent_definitions


def _registry_names() -> frozenset[str]:
    """当前注册表里真实存在的工具名。"""
    return frozenset(tool.name for tool in create_default_tool_registry().list_tools())


def _unknown_tool_names(definitions: list[Any]) -> list[str]:
    """返回 `定义名.字段: 名字` 形式的未知工具名清单；`*` 与空值跳过。"""
    known = _registry_names()
    problems: list[str] = []
    for definition in definitions:
        for field in ("tools", "disallowed_tools"):
            entries = getattr(definition, field, None)
            if not entries:
                continue
            for entry in entries:
                if entry == "*":
                    continue
                if entry not in known:
                    problems.append(f"{definition.name}.{field}: {entry!r}")
    return problems


def test_builtin_agent_tool_names_exist() -> None:
    """内置 agent 的 tools / disallowed_tools 全部命中注册表真名。"""
    problems = _unknown_tool_names(list(get_builtin_agent_definitions()))
    assert not problems, "unknown tool names: " + ", ".join(problems)


def test_unknown_tool_name_is_detected() -> None:
    """守卫自证：写错一个名字必须判红（否则这条守卫是假的）。"""
    fake = SimpleNamespace(
        name="fake",
        tools=["read_file", "Edit"],
        disallowed_tools=["file_write"],
    )
    problems = _unknown_tool_names([fake])
    assert "fake.tools: 'Edit'" in problems
    assert "fake.disallowed_tools: 'file_write'" in problems


def test_wildcard_and_none_are_allowed() -> None:
    """`*` 与 None 表示“全部工具”，不属于未知名字。"""
    fake = SimpleNamespace(name="fake", tools=["*"], disallowed_tools=None)
    assert _unknown_tool_names([fake]) == []
