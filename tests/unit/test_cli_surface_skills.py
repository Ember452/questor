"""技能生效接线测试（C07；`docs/plan/05` DoD①）。

真进程/真 IO：CliSurface 给定 skills_dir 时把发现的技能并入 system prompt（agent 可见即"生效"）；
未给 skills_dir 时 system 不变（不污染既有 run）。EchoProvider 离线，无需密钥。"""

from __future__ import annotations

from pathlib import Path

from questor.providers.fake import EchoProvider
from questor.surfaces.cli import CliSurface


def _skill(root: Path, name: str) -> None:
    d = root / name
    d.mkdir()
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: does a thing well\n---\nbody", encoding="utf-8")


def test_skills_dir_feeds_catalog_into_system_prompt(tmp_path: Path) -> None:
    _skill(tmp_path, "web-research")
    surface = CliSurface(provider=EchoProvider(), skills_dir=tmp_path)
    assert surface.system is not None
    assert "web-research" in surface.system


def test_existing_system_preserved_and_catalog_appended(tmp_path: Path) -> None:
    _skill(tmp_path, "code-review")
    surface = CliSurface(provider=EchoProvider(), system="You are helpful.", skills_dir=tmp_path)
    assert surface.system is not None
    assert surface.system.startswith("You are helpful.")
    assert "code-review" in surface.system


def test_no_skills_dir_leaves_system_unchanged() -> None:
    surface = CliSurface(provider=EchoProvider())
    assert surface.system is None
