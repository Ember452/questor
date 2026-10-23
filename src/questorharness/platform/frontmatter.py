"""Frontmatter parsing shared by agent definitions and plugins.

Pure parsing helpers plus the agent vocabulary they validate against. They live
in ``platform`` because both ``plugins`` (extension layer) and
``runtime.coordinator`` (agent loader) need them, and the previous home made
``plugins`` import ``runtime``.
"""

from __future__ import annotations

from typing import Any

import yaml

__all__ = [
    "AGENT_COLORS",
    "EFFORT_LEVELS",
    "ISOLATION_MODES",
    "MEMORY_SCOPES",
    "PERMISSION_MODES",
    "parse_frontmatter",
    "parse_positive_int",
    "parse_str_list",
]

AGENT_COLORS: frozenset[str] = frozenset(
    {
        "red",
        "green",
        "blue",
        "yellow",
        "purple",
        "orange",
        "cyan",
        "magenta",
        "white",
        "gray",
    }
)

EFFORT_LEVELS: tuple[str, ...] = ("low", "medium", "high")

PERMISSION_MODES: tuple[str, ...] = (
    "default",
    "acceptEdits",
    "bypassPermissions",
    "plan",
    "dontAsk",
)

MEMORY_SCOPES: tuple[str, ...] = ("user", "project", "local")

ISOLATION_MODES: tuple[str, ...] = ("worktree", "remote")

def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from a markdown file.

    Returns a (frontmatter_dict, body) tuple. Uses ``yaml.safe_load`` for
    proper YAML parsing (supports nested structures for hooks, mcpServers, etc.).
    """
    frontmatter: dict[str, Any] = {}
    body = content

    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return frontmatter, body

    end_index: int | None = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = i
            break

    if end_index is None:
        return frontmatter, body

    fm_text = "\n".join(lines[1:end_index])
    try:
        parsed = yaml.safe_load(fm_text)
        if isinstance(parsed, dict):
            frontmatter = parsed
    except yaml.YAMLError:
        # 回退到简单的 key:value 解析
        for fm_line in lines[1:end_index]:
            if ":" in fm_line:
                key, _, value = fm_line.partition(":")
                frontmatter[key.strip()] = value.strip().strip("'\"")

    # 正文是闭合 --- 之后的全部内容
    body = "\n".join(lines[end_index + 1 :]).strip()
    return frontmatter, body

def parse_str_list(raw: Any) -> list[str] | None:
    """Parse a comma-separated string or list into a list of strings."""
    if raw is None:
        return None
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        items = [t.strip() for t in raw.split(",") if t.strip()]
        return items if items else None
    return None

def parse_positive_int(raw: Any) -> int | None:
    """Parse a positive integer from frontmatter, returning None if invalid."""
    if raw is None:
        return None
    try:
        val = int(raw)
        return val if val > 0 else None
    except (TypeError, ValueError):
        return None

# questor: allow R7 -- until W8 adds the mirror test
