"""L3 技能发现与加载（C05；`docs/plan/05` DoD①/T8）。

发现 = 扫目录逐个读 SKILL.md；**单文件失败隔离**：
一个坏 `SKILL.md` 只降级它自己并 WARNING 出声，绝不拖垮整批发现（HARD C6：错误绝不静默）。
发现阶段只到 METADATA（读 frontmatter，不读正文）——正文/资源按 C06 渐进披露（见 `disclosure.py`），
避免整批技能正文无脑进 prompt。只依赖 stdlib（HARD C1/C14）。"""

from __future__ import annotations

import logging
from pathlib import Path

from questor.capabilities.skills.models import DisclosureLevel, Skill
from questor.capabilities.skills.parser import SKILL_FILENAME, parse_frontmatter
from questor.capabilities.skills.validation import validate_directory_name, validate_frontmatter

_log = logging.getLogger("questor.skills")


def load_skill_metadata(skill_dir: Path) -> Skill:
    """读并校验一个技能目录的 frontmatter，返回 METADATA 级 `Skill`；任何不合法即抛。"""
    content = (skill_dir / SKILL_FILENAME).read_text(encoding="utf-8")
    frontmatter, _body = parse_frontmatter(content)
    fm = validate_frontmatter(frontmatter)
    validate_directory_name(skill_dir.name, fm.name)
    return Skill(frontmatter=fm, path=skill_dir, disclosure_level=DisclosureLevel.METADATA)


def discover_skills(search_path: Path) -> list[Skill]:
    """扫描 ``search_path`` 下各子目录，逐个尝试发现技能；坏文件出声跳过、其余照常返回。"""
    if not search_path.is_dir():
        raise FileNotFoundError(f"Skill search path is not a directory: {search_path}")

    skills: list[Skill] = []
    for child in sorted(search_path.iterdir()):
        if not child.is_dir():
            continue  # 顶层文件：非技能目录，忽略
        if not (child / SKILL_FILENAME).is_file():
            continue  # 无 SKILL.md 的普通目录：不是技能尝试，静默跳过（区别于"坏技能"）
        try:
            skills.append(load_skill_metadata(child))
        except Exception as exc:  # noqa: BLE001 - 单个坏技能必须降级而非中断整批发现（C6）
            _log.warning("Failed to load skill from %s: %s", child, exc)
    return skills
