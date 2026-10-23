"""Contract tests for the layout rules: every rule must go red and green.

``check_layout --self-test`` proves the rules can detect a violation in memory.
This file proves the same through the filesystem + git layer the guard really
uses (``git ls-files``), one temporary repository per case, so a broken scan
caliber cannot hide behind a passing in-memory test.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "guards"))

import _layout_rules as rules  # noqa: E402

CRITICAL = (
    "bootstrap",
    "capabilities",
    "commands",
    "config",
    "contracts",
    "engine",
    "providers",
    "runtime",
    "surfaces",
)


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)


def _write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _base_repo(root: Path) -> None:
    """A tree that passes R1-R8: nine mapped packages, one mirrored module each."""
    _write(root, "tests/unit/test_thing.py", "def test_thing():\n    assert True\n")
    _write(root, "tests/unit/test_ok.py", "def test_ok():\n    assert True\n")
    _write(root, "tests/unit/test_registry.py", "def test_registry():\n    assert True\n")
    for package in CRITICAL:
        base = f"src/questorharness/{package}"
        _write(root, f"{base}/__init__.py", '"""Facade."""\n\n__all__ = ["thing"]\n')
        _write(root, f"{base}/thing.py", '"""Leaf."""\n\nthing = 1\n')
        _write(root, f"{base}/AGENTS.md", "# map\n\n关键文件：`__init__.py`、`thing.py`\n")
    _write(root, "src/questorharness/surfaces/channels/__init__.py", '"""Adapters."""\n')
    _write(root, "src/questorharness/commands/registry.py", '"""Registry."""\n')
    _write(root, "src/questorharness/commands/families/ok.py", '"""Family."""\n')
    _init_repo(root)


def _repo(tmp_path: Path, extra: dict[str, str] | None = None) -> Path:
    root = tmp_path / "repo"
    root.mkdir(parents=True, exist_ok=True)
    _base_repo(root)
    for relative, text in (extra or {}).items():
        _write(root, relative, text)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    return root


def test_base_repo_is_green(tmp_path: Path) -> None:
    """The fixture itself must be clean, otherwise every red case is meaningless."""
    root = _repo(tmp_path)
    # Synthetic repositories hold no exemptions, so the ratchet is switched off
    # here; test_budget_ratchet_is_silent_when_counts_match covers the real one.
    violations, problems = rules.collect_with_budgets(root, budget={}, pinned_functions=0)
    assert violations == [], [item.render() for item in violations]
    assert problems == [], problems


def test_r1_fanout_red_then_green(tmp_path: Path) -> None:
    extra = {f"src/questorharness/crowded/m{index}.py": "VALUE = 1\n" for index in range(31)}
    root = _repo(tmp_path, extra)
    assert any(item.rule == "R1" and item.severity == "fail" for item in rules.rule_r1_fanout(root))
    del_violation = rules.rule_r1_fanout(_repo(tmp_path / "green"))
    assert not [item for item in del_violation if item.severity == "fail"]


def test_r2_lines_red_then_green(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"src/questorharness/commands/fat.py": "\n".join(["X = 1"] * 1501) + "\n"})
    assert any(item.rule == "R2" for item in rules.rule_r2_lines(root))
    assert not rules.rule_r2_lines(_repo(tmp_path / "green"))


def test_r3_banned_name_red_then_green(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"src/questorharness/commands/manager.py": "VALUE = 1\n"})
    assert any(item.rule == "R3" for item in rules.rule_r3_names(root))
    assert not rules.rule_r3_names(_repo(tmp_path / "green"))


def test_r4_facade_red_then_green(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"src/questorharness/commands/__init__.py": "def helper():\n    return 1\n"})
    assert any(item.rule == "R4" for item in rules.rule_r4_facade(root))
    assert not rules.rule_r4_facade(_repo(tmp_path / "green"))


def test_r5_exports_red_then_green(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"src/questorharness/loose/__init__.py": ""})
    assert any(item.rule == "R5" for item in rules.rule_r5_exports(root))
    assert not rules.rule_r5_exports(_repo(tmp_path / "green"))


def test_r6_map_red_then_green(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"src/questorharness/engine/AGENTS.md": "# map\n无关键文件\n"})
    assert any("engine" in item.path for item in rules.rule_r6_maps(root))
    assert not [item for item in rules.rule_r6_maps(_repo(tmp_path / "green")) if "engine" in item.path]


def test_r7_mirror_red_then_green(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"src/questorharness/engine/unmirrored.py": "VALUE = 1\n"})
    assert any("unmirrored" in item.path for item in rules.rule_r7_mirror(root))
    assert not any("unmirrored" in item.path for item in rules.rule_r7_mirror(_repo(tmp_path / "green")))


def test_r8_complexity_red_then_green(tmp_path: Path) -> None:
    branches = "\n".join(f"    if x == {index}:\n        return {index}" for index in range(21))
    root = _repo(
        tmp_path,
        {"src/questorharness/engine/heavy.py": f"def heavy(x):\n{branches}\n    return -1\n"},
    )
    violations, _ = rules.rule_r8_complexity(root)
    assert any(item.rule == "R8" for item in violations)
    green, _ = rules.rule_r8_complexity(_repo(tmp_path / "green"))
    assert not green


def test_exemption_without_reason_is_red(tmp_path: Path) -> None:
    """A comment without a deletion condition is not an exemption."""
    source = "VALUE = 1\n# questor: allow R7\n"
    root = _repo(tmp_path, {"src/questorharness/engine/unreasoned.py": source})
    _, problems = rules.collect_with_budgets(root, budget={}, pinned_functions=0)
    assert any("malformed exemption" in item for item in problems), problems


def test_exemption_budget_cannot_grow(tmp_path: Path) -> None:
    """Adding more R3 comments than the pinned budget is a failure."""
    extra = {}
    for index in range(rules.EXEMPTION_BUDGET["R3"] + 1):
        extra[f"src/questorharness/engine/manager{index}.py"] = (
            "VALUE = 1\n# questor: allow R3 -- until W9 rename wave\n"
        )
    root = _repo(tmp_path, extra)
    _, problems = rules.collect_with_budgets(root)
    assert any("debt was added" in item for item in problems), problems


def test_exemption_budget_cannot_be_left_high() -> None:
    """Paying off debt without lowering the budget is the same size of failure."""
    budget = {"R3": 22}
    stale = rules.budget_problems({"R3": 21}, 0, budget=budget, pinned_functions=0)
    assert any("R3: 21 exemptions < budget 22" in item for item in stale), stale
    assert any("budget was not lowered" in item for item in stale), stale


def test_budget_ratchet_is_silent_when_counts_match() -> None:
    """The ratchet must not fire when the budget matches reality in both fields."""
    counts = rules.exemptions_by_rule(REPO_ROOT.resolve())
    pinned = rules.R8_EXEMPT_FUNCTIONS
    assert rules.budget_problems(counts, pinned) == [], rules.budget_problems(counts, pinned)
    off_by_one = rules.budget_problems(counts, pinned + 1)
    assert off_by_one and all(item.startswith("R8") for item in off_by_one), off_by_one


@pytest.mark.parametrize("rule", ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"])
def test_every_rule_has_a_green_counterpart(rule: str, tmp_path: Path) -> None:
    """Every rule must be silent on the clean fixture."""
    root = _repo(tmp_path)
    if rule == "R8":
        violations, exempted = rules.rule_r8_complexity(root)
        assert not violations and exempted == 0
        return
    function = {
        "R1": rules.rule_r1_fanout,
        "R2": rules.rule_r2_lines,
        "R3": rules.rule_r3_names,
        "R4": rules.rule_r4_facade,
        "R5": rules.rule_r5_exports,
        "R6": rules.rule_r6_maps,
        "R7": rules.rule_r7_mirror,
    }[rule]
    assert not function(root), f"{rule} is not silent on the clean fixture"
