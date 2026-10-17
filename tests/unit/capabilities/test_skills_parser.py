"""SKILL.md frontmatter 解析的判红用例（C03，TDD）。

真源决策见 `docs/plan/05-p5-skills-mcp.md §2 T8` 与 §0.2 Skills 扫描行（改造 crewAI
`skills/parser.py:39-127`，但用**依赖最小**的严格解析替代 `yaml.safe_load`——本仓未在
pyproject 声明 pyyaml，依赖 transitive 会随上游漂移而消失；SKILL.md frontmatter 只需扁平
`key: scalar` 与可选内联 list，手写严格解析足够且对不支持结构 fail-closed，绝不误解析）。
"""

from __future__ import annotations

import pytest

from questor.capabilities.skills.parser import SkillParseError, parse_frontmatter


def test_parses_flat_scalar_frontmatter_and_body() -> None:
    content = "---\nname: web-research\ndescription: look things up\n---\n# Body text\nhello"
    frontmatter, body = parse_frontmatter(content)
    assert frontmatter == {"name": "web-research", "description": "look things up"}
    assert body == "# Body text\nhello"


def test_value_with_colon_splits_only_on_first_delimiter() -> None:
    content = "---\ndescription: url: http://x:8080\n---\nbody"
    frontmatter, _ = parse_frontmatter(content)
    assert frontmatter["description"] == "url: http://x:8080"


def test_quoted_scalar_value_is_unquoted() -> None:
    content = '---\nname: "quoted name"\n---\nbody'
    frontmatter, _ = parse_frontmatter(content)
    assert frontmatter["name"] == "quoted name"


def test_inline_flow_list_value_parsed() -> None:
    content = "---\nname: s\nallowed-tools: [Read, Write]\n---\nbody"
    frontmatter, _ = parse_frontmatter(content)
    assert frontmatter["allowed-tools"] == ["Read", "Write"]


def test_missing_opening_delimiter_raises() -> None:
    with pytest.raises(SkillParseError):
        parse_frontmatter("name: s\n---\nbody")


def test_missing_closing_delimiter_raises() -> None:
    with pytest.raises(SkillParseError):
        parse_frontmatter("---\nname: s\nno closing delimiter here")


def test_non_key_value_line_raises() -> None:
    # 缩进块映射 / 列表项等不支持结构必须 fail-closed，而不是悄悄产生错误 dict。
    with pytest.raises(SkillParseError):
        parse_frontmatter("---\n  indented: bad\n---\nbody")


def test_empty_frontmatter_mapping_is_allowed_but_body_required_shape() -> None:
    # `---` 紧接 `---`：合法但空映射；由上层校验必填 name/description（C04），本函数不误判为错。
    frontmatter, body = parse_frontmatter("---\n---\nbody only")
    assert frontmatter == {}
    assert body == "body only"
