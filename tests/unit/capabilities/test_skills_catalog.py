"""技能目录渲染的判红用例（C07；`docs/plan/05` DoD①/T8）。

"生效"的可测最小实现：发现的技能名+描述渲染成 catalog 供 agent（system prompt）消费。
描述走共享 `bound_description`（C08）——过长/含控制字符被有界净化，别把注入面原样搬进 prompt。
用 tmp_path 真文件。"""

from __future__ import annotations

from pathlib import Path

from questor.capabilities.skills.catalog import build_skill_catalog


def _skill(root: Path, name: str, description: str) -> None:
    d = root / name
    d.mkdir()
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\nbody", encoding="utf-8")


def test_none_and_missing_dir_yield_empty_catalog() -> None:
    assert build_skill_catalog(None) == ""
    assert build_skill_catalog(Path("/no/such/dir")) == ""


def test_catalog_lists_discovered_skills(tmp_path: Path) -> None:
    _skill(tmp_path, "web-research", "look things up online")
    _skill(tmp_path, "code-review", "review diffs for bugs")
    catalog = build_skill_catalog(tmp_path)
    assert "- web-research: look things up online" in catalog
    assert "- code-review: review diffs for bugs" in catalog


def test_broken_only_dir_yields_empty_catalog(tmp_path: Path) -> None:
    bad = tmp_path / "broken"
    bad.mkdir()
    (bad / "SKILL.md").write_text("not valid frontmatter", encoding="utf-8")  # 缺 --- → discover 跳过
    assert build_skill_catalog(tmp_path) == ""


def test_overlong_description_is_bounded_in_catalog(tmp_path: Path) -> None:
    _skill(tmp_path, "longdesc", "z" * 500)
    catalog = build_skill_catalog(tmp_path)
    # 单条 catalog 行不应原样塞入 500 字符（走 bound_description 有界）；整体长度受限。
    assert len(catalog) < 500
