"""L3 SKILL.md frontmatter 解析（C03；`docs/plan/05` T8/T9）。

设计取舍（相对 crewAI `skills/parser.py:39-127` 的 `yaml.safe_load`）：本仓未在
`pyproject` 声明 pyyaml，依赖 transitive 会随上游升级消失（supply-chain 隐患），且
Agent Skills 的 frontmatter 只需扁平 ``key: scalar`` 与可选内联 list——故用**严格、依赖最小**
的手写解析：只接受 ``key: value`` 行，任何缩进块映射 / 顶层列表项 / 无冒号行一律
fail-closed 抛 `SkillParseError`（绝不悄悄产出错误 dict，也不误吞畸形文件）。

依赖：仅 stdlib。失败语义：结构不合法即抛 `SkillParseError`（ValueError 子类），由上层
`loader.discover_skills` 逐文件降级并出声（C6）。"""

from __future__ import annotations

from typing import Final

#: 技能目录内的约定文件名（`capabilities/skills/README.md` 钉死）。
SKILL_FILENAME: Final[str] = "SKILL.md"

#: frontmatter 分隔符（首行与闭合行都是单独一行的 ``---``）。
_DELIMITER: Final[str] = "---"


class SkillParseError(ValueError):
    """SKILL.md 解析失败的归一错误（缺分隔符 / 不支持的结构 / 非法键）。"""


def _parse_scalar(raw: str) -> object:
    """把一个 frontmatter 值文本解析为 str / list[str] / None。

    只支持三种形状：内联流式 list（``[a, b]``）、成对引号包裹的标量、裸标量。其余原样返回，
    调用方保证 ``raw`` 已是去掉 ``key:`` 与行首空白后的值段。
    """
    value = raw.strip()
    if value == "":
        return None
    # 内联 list：[a, b, c]（元素按逗号切、去空白、丢空项）。
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1]
        return [item.strip() for item in inner.split(",") if item.strip()]
    # 成对引号：去掉外层引号（仅当首尾同为 " 或 ' 且长度≥2）。
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _parse_frontmatter_line(line: str) -> tuple[str, object]:
    """把一行解析为 ``(key, value)``；不支持的结构抛 `SkillParseError`。"""
    # 缩进行 = 块映射 / 续行，本严格解析器不接受（fail-closed，避免误解析）。
    if line[:1] in (" ", "\t"):
        raise SkillParseError(f"frontmatter line must not be indented: {line!r}")
    # 顶层列表项（``- foo``）不是 ``key: value``，同样拒绝。
    if line.startswith("-"):
        raise SkillParseError(f"frontmatter block sequences are not supported: {line!r}")
    key, sep, rest = line.partition(":")
    if not sep:
        raise SkillParseError(f"frontmatter line must be 'key: value': {line!r}")
    key = key.strip()
    if not key or not key.replace("_", "").replace("-", "").isalnum():
        raise SkillParseError(f"frontmatter has an invalid key: {line!r}")
    return key, _parse_scalar(rest)


def parse_frontmatter(content: str) -> tuple[dict[str, object], str]:
    """把 SKILL.md 全文切成 ``(frontmatter, body)``。

    规则：首行必须是单独的 ``---``；随后第一个单独的 ``---`` 为闭合行；两行之间为
    ``key: value`` frontmatter；闭合行之后（strip）为 markdown body。缺任一分隔符或
    frontmatter 行结构非法 → `SkillParseError`。空 frontmatter（``---`` 紧接 ``---``）合法，
    返回 ``({}, body)``——必填字段的存在性由上层 `validate` 判（C04），本函数只管形状。
    """
    text = content.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if not lines or lines[0].strip() != _DELIMITER:
        raise SkillParseError("SKILL.md must start with a '---' frontmatter delimiter line")

    closing_index = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == _DELIMITER:
            closing_index = i
            break
    if closing_index == -1:
        raise SkillParseError("SKILL.md missing the closing '---' frontmatter delimiter")

    frontmatter: dict[str, object] = {}
    for line in lines[1:closing_index]:
        if line.strip() == "":
            continue
        key, value = _parse_frontmatter_line(line)
        frontmatter[key] = value
    body = "\n".join(lines[closing_index + 1 :]).strip()
    return frontmatter, body
