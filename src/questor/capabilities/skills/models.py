"""L3 技能数据模型（C04/C06/C07；`docs/plan/05` T8）。

只放数据与不变式，不 import providers/surfaces（HARD C1/C14）。渐进披露等级（C06）与
`Skill` 容器在此定义；frontmatter 由 `validation.validate_frontmatter` 构型。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import IntEnum
from pathlib import Path


class DisclosureLevel(IntEnum):
    """技能信息渐进披露层级：METADATA/INSTRUCTIONS/RESOURCES 三档。

    越高越"贵"（进 prompt 的字节越多）：发现阶段只读 METADATA（frontmatter），激活才读
    INSTRUCTIONS（正文），需要资源清单才升到 RESOURCES——避免整批技能正文无脑塞进上下文。"""

    METADATA = 0
    INSTRUCTIONS = 1
    RESOURCES = 2


@dataclass(frozen=True, slots=True)
class SkillFrontmatter:
    """SKILL.md frontmatter 的已校验视图。``name``/``description`` 必填，其余可选。"""

    name: str
    description: str
    version: str | None = None
    author: str | None = None
    license: str | None = None


@dataclass(frozen=True, slots=True)
class Skill:
    """一个已发现技能；``disclosure_level`` 决定 ``body``/``resources`` 是否已载入（渐进披露，C06）。

    发现阶段只到 METADATA（读 frontmatter），激活才读 INSTRUCTIONS（正文 body），需要资源清单
    才升到 RESOURCES——避免整批技能正文无脑塞进上下文。"""

    frontmatter: SkillFrontmatter
    path: Path
    disclosure_level: DisclosureLevel = DisclosureLevel.METADATA
    body: str | None = None
    resources: tuple[str, ...] = ()

    def with_disclosure(self, *, level: DisclosureLevel, body: str | None = None, resources: tuple[str, ...] | None = None) -> Skill:
        """返回升级后的新实例（frozen：不改原对象）。"""
        return replace(
            self,
            disclosure_level=level,
            body=body if body is not None else self.body,
            resources=resources if resources is not None else self.resources,
        )
