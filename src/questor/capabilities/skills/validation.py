"""L3 技能 frontmatter 校验（C04；`docs/plan/05` T8/T9）。

改造 crewAI `skills/validation.py:13-56`：name 小写连字符正则、长度上界、目录名==声明名。
失败即抛 `SkillParseError`（与解析同族），交 `loader.discover_skills` 逐文件降级出声，绝不误纳。
只依赖 stdlib（HARD C1/C14）。"""

from __future__ import annotations

import re

from questor.capabilities.skills.models import SkillFrontmatter
from questor.capabilities.skills.parser import SkillParseError

#: name 约束（Agent Skills 规范：小写字母数字 + 单连字符分段）。
MAX_SKILL_NAME_LENGTH = 64
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _require_str(fm: dict[str, object], key: str, *, required: bool) -> str | None:
    """取一个必须为字符串的 frontmatter 字段；缺失/类型不符按 required 决定抛或返回 None。"""
    if key not in fm:
        if required:
            raise SkillParseError(f"SKILL.md frontmatter missing required field '{key}'")
        return None
    value = fm[key]
    if not isinstance(value, str):
        raise SkillParseError(f"SKILL.md frontmatter field '{key}' must be a string, got {type(value).__name__}")
    return value


def validate_frontmatter(fm: dict[str, object]) -> SkillFrontmatter:
    """把解析出的 frontmatter 映射校验为 `SkillFrontmatter`；任一非法即抛 `SkillParseError`。"""
    name = _require_str(fm, "name", required=True)
    description = _require_str(fm, "description", required=True)
    assert name is not None and description is not None  # required=True 已保证非 None
    if len(name) > MAX_SKILL_NAME_LENGTH:
        raise SkillParseError(f"skill name exceeds {MAX_SKILL_NAME_LENGTH} chars: {name!r}")
    if not SKILL_NAME_PATTERN.match(name):
        raise SkillParseError(
            f"skill name must match ^[a-z0-9]+(?:-[a-z0-9]+)*$ (lowercase, hyphen-separated): {name!r}"
        )
    return SkillFrontmatter(
        name=name,
        description=description,
        version=_require_str(fm, "version", required=False),
        author=_require_str(fm, "author", required=False),
        license=_require_str(fm, "license", required=False),
    )


def validate_directory_name(dir_name: str, skill_name: str) -> None:
    """技能目录名必须等于 frontmatter 声明的 name（否则发现→引用会错位）。"""
    if dir_name != skill_name:
        raise ValueError(f"directory name '{dir_name}' does not match skill name '{skill_name}'")
