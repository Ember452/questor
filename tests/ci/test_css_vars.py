"""token 迁移守卫：`var(--x)` 必须已定义；alias 必须覆盖全部 DeepCode 旧变量。"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
THEME = REPO / "apps/web/src/shared/theme"
SRC = REPO / "apps/web/src"
FILES = ("tokens.deepcode.css", "tokens.reasonix.css", "alias.css")

DECL = re.compile(r"(--[a-z0-9-]+)\s*:")
BARE_VAR = re.compile(r"var\(\s*(--[a-z0-9-]+)\s*\)")
ANY_VAR = re.compile(r"var\(\s*(--[a-z0-9-]+)\s*[,)]")


def defined_names() -> set[str]:
    names: set[str] = set()
    for name in FILES:
        names |= set(DECL.findall((THEME / name).read_text(encoding="utf-8")))
    return names


def undefined_bare_vars() -> list[str]:
    """没有 fallback 的 var(--x) 必须已定义；带 fallback 视为自足。"""
    known = defined_names()
    problems: list[str] = []
    for path in SRC.rglob("*.css"):
        for name in BARE_VAR.findall(path.read_text(encoding="utf-8")):
            if name not in known:
                problems.append(f"{path.relative_to(SRC)}: {name}")
    return problems


def alias_coverage() -> list[str]:
    deepcode = set(DECL.findall((THEME / "tokens.deepcode.css").read_text(encoding="utf-8")))
    alias = set(DECL.findall((THEME / "alias.css").read_text(encoding="utf-8")))
    return sorted(deepcode - alias)


def test_every_bare_var_is_defined() -> None:
    assert undefined_bare_vars() == []


def test_alias_covers_every_deepcode_variable() -> None:
    missing = alias_coverage()
    assert missing == [], f"alias 漏登记：{missing}"


def test_any_var_parses_with_fallback() -> None:
    """自证：`var(--x)` 与 `var(--x, #fff)` 都必须被识别为对 --x 的引用。"""
    sample = "color: var(--a); background: var(--b, #000);"
    assert ANY_VAR.findall(sample) == ["--a", "--b"]
    assert BARE_VAR.findall(sample) == ["--a"]
