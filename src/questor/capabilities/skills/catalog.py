"""L3 技能目录渲染（C07；`docs/plan/05` DoD①）。

把发现的技能名+描述渲染成一段可读目录，供 agent 的 system prompt 消费——这是"丢一个
SKILL.md 即被发现并**生效**"的最小、可测实现：生效 = 该技能进入 agent 可见的能力清单。
描述走共享 `bound_description`（C08）做有界净化，绝不把过长/含注入字符的原文原样搬进 prompt
（C18/C20 的有界精神）。技能无机器可调用 schema，故不臆造成 ToolSpec 工具（AGENTS §2 YAGNI）。
只依赖 stdlib + 本层 `skills`/`tools.registry`（HARD C1/C14）。"""

from __future__ import annotations

from pathlib import Path

from questor.capabilities.skills.loader import discover_skills
from questor.capabilities.tools.registry import bound_description

#: 目录里每条技能描述的展示上限（防单条撑爆 prompt）。
_CATALOG_DESC_MAX = 200

_HEADER = "Available skills:"


def build_skill_catalog(search_path: Path | None) -> str:
    """发现技能并渲染成目录字符串；无目录/无有效技能 → 空串（不报错，静默无技能是合法的）。"""
    if search_path is None or not search_path.is_dir():
        return ""
    skills = discover_skills(search_path)
    if not skills:
        return ""
    lines = [
        f"- {skill.frontmatter.name}: {bound_description(skill.frontmatter.description, name=skill.frontmatter.name, max_chars=_CATALOG_DESC_MAX)}"
        for skill in sorted(skills, key=lambda s: s.frontmatter.name)
    ]
    return "\n".join([_HEADER, *lines])
