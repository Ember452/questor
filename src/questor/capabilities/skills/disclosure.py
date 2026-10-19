"""L3 技能渐进披露（C06；`docs/plan/05` T8）。

发现阶段只到 METADATA（见 `loader.py`）；本模块按需升级：
- INSTRUCTIONS：读 SKILL.md 正文 body；
- RESOURCES：列 scripts/references/assets 下文件清单。
正文软上限 ``_MAX_BODY_CHARS``：超阈**只告警不失败**——大正文挤占上下文是 prompt 注入/膨胀面
（C18/C20 有界精神），但不因体积直接拒载。只依赖 stdlib（C1/C14）。"""

from __future__ import annotations

import logging

from questor.capabilities.skills.models import DisclosureLevel, Skill
from questor.capabilities.skills.parser import SKILL_FILENAME, parse_frontmatter

_log = logging.getLogger("questor.skills")

#: 正文软上限：超阈告警（防 prompt 膨胀）。
_MAX_BODY_CHARS = 50_000

#: 资源清单扫描的子目录（相对技能目录）。
_RESOURCE_DIRS = ("scripts", "references", "assets")


def load_skill_instructions(skill: Skill) -> Skill:
    """升到 INSTRUCTIONS：读 SKILL.md 正文 body。已 >= INSTRUCTIONS 则原样返回（idempotent）。"""
    if skill.disclosure_level >= DisclosureLevel.INSTRUCTIONS:
        return skill
    content = (skill.path / SKILL_FILENAME).read_text(encoding="utf-8")
    _, body = parse_frontmatter(content)
    if len(body) > _MAX_BODY_CHARS:
        _log.warning(
            "SKILL.md body for '%s' is %d chars (threshold %d); large bodies can inflate the prompt",
            skill.frontmatter.name,
            len(body),
            _MAX_BODY_CHARS,
        )
    return skill.with_disclosure(level=DisclosureLevel.INSTRUCTIONS, body=body)


def load_skill_resources(skill: Skill) -> Skill:
    """升到 RESOURCES：列 scripts/references/assets 下的文件（相对技能目录）；缺 INSTRUCTIONS 先补。"""
    if skill.disclosure_level >= DisclosureLevel.RESOURCES:
        return skill
    if skill.disclosure_level < DisclosureLevel.INSTRUCTIONS:
        skill = load_skill_instructions(skill)
    resources: list[str] = []
    for sub_name in _RESOURCE_DIRS:
        sub_dir = skill.path / sub_name
        if not sub_dir.is_dir():
            continue
        resources.extend(str(f.relative_to(skill.path)) for f in sorted(sub_dir.rglob("*")) if f.is_file())
    return skill.with_disclosure(level=DisclosureLevel.RESOURCES, resources=tuple(resources))
