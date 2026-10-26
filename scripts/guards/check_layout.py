#!/usr/bin/env python3
"""Keep the file-level layout from regressing (R1-R8 plus the Phase 2 pins).

Two groups of rules live behind one entry point:

* the Phase 2 pins that cost a migration wave to make (removed packages stay
  removed, ``surfaces/`` holds renderer adapters only, no dropped UI toolkit,
  the two command budgets);
* R1-R8 from ADR-0003 section 8, implemented in ``_layout_rules.py`` so the
  contract tests can drive them without going through the CLI.

Every rule scans ``git ls-files`` (via ``_guard_kit.tracked_files``); untracked
scratch output can never make this guard red or green. Existing debt is carried
by inline ``# questor: allow <RULE> -- <until W..>`` comments; a missing or
reasonless comment is itself a failure, and the number of comments per rule is
pinned in ``_layout_rules.EXEMPTION_BUDGET`` so exemptions can only go down.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

try:
    from ._guard_kit import (
        EXIT_CONFIG,
        EXIT_OK,
        EXIT_RED,
        GuardConfigError,
        count_lines,
        fail_on_empty,
        read_text,
        run_self_test,
        tracked_files,
        walk_py,
    )
    from ._layout_rules import (
        Violation,
        collect_with_budgets,
        exemptions_by_rule,
        rule_r1_fanout,
        rule_r2_lines,
        rule_r3_names,
        rule_r4_facade,
        rule_r5_exports,
        rule_r6_maps,
        rule_r7_mirror,
        rule_r8_complexity,
    )
except ImportError:  # direct script execution
    from _guard_kit import (  # type: ignore[no-redef]
        EXIT_CONFIG,
        EXIT_OK,
        EXIT_RED,
        GuardConfigError,
        count_lines,
        fail_on_empty,
        read_text,
        run_self_test,
        tracked_files,
        walk_py,
    )
    from _layout_rules import (  # type: ignore[no-redef]
        Violation,
        collect_with_budgets,
        exemptions_by_rule,
        rule_r1_fanout,
        rule_r2_lines,
        rule_r3_names,
        rule_r4_facade,
        rule_r5_exports,
        rule_r6_maps,
        rule_r7_mirror,
        rule_r8_complexity,
    )

REPO_ROOT = Path(__file__).resolve().parents[2]

REMOVED_PACKAGES = (
    "src/questorharness/ui",
    "src/questorharness/personalization",
    "src/questorharness/surfaces/ipc",
)
ALLOWED_SURFACES = {"channels"}
# The global line budget now lives in R2 (fail >1500, ratchet 1001-1500): plan 01
# widened 1200 to 1500 once, and R2 is the only place allowed to decide it.
FILE_BUDGETS = {"src/questorharness/commands/registry.py": 250}
DIR_BUDGETS = {"src/questorharness/commands/families": 600}
DROPPED_UI_IMPORTS = ("textual", "prompt_toolkit")
# prompt-toolkit 以终端瘦客户端的输入层身份回归（ADR-0005 Updated 2026-10-26）；
# textual 以**终端产品本体**身份回归（2026-10-26：行式 prompt 给不了带框输入框、
# 固定状态栏与可靠候选菜单，OpenHarness 同构迁移）。两者都只放行终端宿主这一层，
# 引擎/能力/surfaces 仍然判红。
# 键以 "/" 结尾 = 目录级放行，否则为单文件放行。
DROPPED_UI_EXCEPTIONS = {
    "src/questorharness/bootstrap/hosts/terminal_client.py": {"prompt_toolkit"},
    "src/questorharness/bootstrap/hosts/terminal/": {"prompt_toolkit"},
    "src/questorharness/bootstrap/hosts/tui/": {"textual"},
}


def _exempt_modules(rel: str) -> set[str]:
    """某文件被放行可 import 的"已删 UI"包（单文件键 + 目录前缀键的并集）。"""

    allowed = set(DROPPED_UI_EXCEPTIONS.get(rel, set()))
    for path, modules in DROPPED_UI_EXCEPTIONS.items():
        if path.endswith("/") and rel.startswith(path):
            allowed |= modules
    return allowed


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def find_removed_packages(root: Path) -> list[str]:
    """Report removed packages only when Python sources are present again.

    A leftover ``__pycache__`` directory is not tracked and not a regression.
    """
    found = []
    for name in REMOVED_PACKAGES:
        directory = root / name
        if directory.is_dir() and any(directory.rglob("*.py")):
            found.append(name)
    return found


def find_unexpected_surfaces(root: Path) -> list[str]:
    surfaces = root / "src/questorharness/surfaces"
    if not surfaces.is_dir():
        raise GuardConfigError(f"surfaces package is missing: {surfaces}")
    found = [
        child.name
        for child in sorted(surfaces.iterdir())
        if child.is_dir() and child.name != "__pycache__" and child.name not in ALLOWED_SURFACES
    ]
    return found


def find_dropped_ui_imports(root: Path) -> list[str]:
    hits: list[str] = []
    for path in walk_py(root / "src"):
        text = read_text(path)
        for module in DROPPED_UI_IMPORTS:
            for marker in (f"import {module}", f"from {module}"):
                if marker in text:
                    hits.append(f"{_rel(path, root)}: {marker}")
                    break
        # 登记的例外文件/目录可以 import 特定的"已删 UI"包（如 prompt_toolkit 作为输入层）。
        rel = _rel(path, root)
        for module in _exempt_modules(rel):
            hits = [h for h in hits if not (h.startswith(rel) and module in h)]
    return hits


def find_oversized_files(root: Path) -> list[str]:
    problems: list[str] = []
    for relative, budget in FILE_BUDGETS.items():
        path = root / relative
        if not path.exists():
            problems.append(f"{relative}: missing")
            continue
        lines = count_lines(path)
        if lines > budget:
            problems.append(f"{relative}: {lines} lines > {budget}")

    for relative, budget in DIR_BUDGETS.items():
        directory = root / relative
        if not directory.is_dir():
            problems.append(f"{relative}: missing")
            continue
        for path in sorted(directory.glob("*.py")):
            lines = count_lines(path)
            if lines > budget:
                problems.append(f"{_rel(path, root)}: {lines} lines > {budget}")
    return problems


def collect_problems(root: Path) -> list[str]:
    """Phase 2 pins. R1-R8 live in ``_layout_rules``."""
    return [
        *(f"removed package came back: {name}" for name in find_removed_packages(root)),
        *(f"unexpected package under surfaces/: {name}" for name in find_unexpected_surfaces(root)),
        *(f"dropped UI toolkit imported: {hit}" for hit in find_dropped_ui_imports(root)),
        *find_oversized_files(root),
    ]


def _violations(root: Path) -> tuple[list[Violation], list[str]]:
    violations, problems = collect_with_budgets(root)
    return violations, problems


def _self_test() -> int:
    """Eight cases, one per rule, each proving the rule can go red and green."""
    cases: list[tuple[str, bool, str]] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        package = root / "src/questorharness"
        (package / "surfaces/channels").mkdir(parents=True)
        (package / "commands/families").mkdir(parents=True)
        (package / "commands/registry.py").write_text("def x():\n    return 1\n", encoding="utf-8")
        (package / "commands/families/ok.py").write_text("VALUE = 1\n", encoding="utf-8")
        (package / "surfaces/__init__.py").write_text('__all__ = ["x"]\n', encoding="utf-8")
        (package / "bootstrap").mkdir()
        (package / "bootstrap/__init__.py").write_text('__all__ = ["x"]\n', encoding="utf-8")
        (package / "bootstrap/AGENTS.md").write_text(
            "# map\n关键文件：`__init__.py`、`thing.py`\n", encoding="utf-8"
        )
        (package / "bootstrap/thing.py").write_text("VALUE = 1  # questor: allow R7 -- until W8\n", encoding="utf-8")
        _git_init(root)

        fresh = collect_problems(root)
        cases.append(("phase2-pins-clean", fresh == [], f"{fresh}"))

        # R1: 31 sources in one directory fail, 20 only warn.
        crowded = package / "crowded"
        crowded.mkdir()
        for index in range(31):
            (crowded / f"m{index}.py").write_text("VALUE = 1\n", encoding="utf-8")
        _git_add(root)
        r1 = rule_r1_fanout(root)
        cases.append(
            (
                "R1-fanout",
                any(item.severity == "fail" and item.rule == "R1" for item in r1),
                f"{[item.render() for item in r1]}",
            )
        )
        for index in range(31, 20, -1):
            (crowded / f"m{index - 1}.py").unlink()
        _git_add(root)
        r1_warn = rule_r1_fanout(root)
        cases.append(
            (
                "R1-warn-only",
                bool(r1_warn) and all(item.severity == "warn" for item in r1_warn),
                f"{[item.render() for item in r1_warn]}",
            )
        )

        # R2: a 1501 line file fails, a 1200 line file needs a pin.
        fat = package / "fat.py"
        fat.write_text("\n".join(["X = 1"] * 1501) + "\n", encoding="utf-8")
        _git_add(root)
        r2 = rule_r2_lines(root)
        cases.append(("R2-lines", any(item.rule == "R2" for item in r2), f"{[item.render() for item in r2]}"))
        fat.write_text("\n".join(["X = 1"] * 1200) + "\n", encoding="utf-8")
        _git_add(root)
        r2_unpinned = rule_r2_lines(root)
        cases.append(
            (
                "R2-ratchet",
                any("without an R2 exemption" in item.message for item in r2_unpinned),
                f"{[item.render() for item in r2_unpinned]}",
            )
        )
        fat.unlink()

        # R3: banned file name.
        banned = package / "manager.py"
        banned.write_text("VALUE = 1\n", encoding="utf-8")
        _git_add(root)
        r3 = rule_r3_names(root)
        cases.append(("R3-banned-name", any(item.rule == "R3" for item in r3), f"{[item.render() for item in r3]}"))
        banned.unlink()

        # R4: logic inside __init__.py.
        facade = package / "facade"
        facade.mkdir()
        (facade / "__init__.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
        _git_add(root)
        r4 = rule_r4_facade(root)
        cases.append(("R4-facade-logic", any(item.rule == "R4" for item in r4), f"{[item.render() for item in r4]}"))
        (facade / "__init__.py").write_text('"""facade."""\n\nfrom .impl import x\n\n__all__ = ["x"]\n', encoding="utf-8")
        (facade / "impl.py").write_text("x = 1\n", encoding="utf-8")
        _git_add(root)
        cases.append(("R4-facade-clean", not rule_r4_facade(root), f"{[item.render() for item in rule_r4_facade(root)]}"))

        # R5: top-level package without __all__.
        bare = package / "bare"
        bare.mkdir()
        (bare / "__init__.py").write_text("", encoding="utf-8")
        _git_add(root)
        r5 = rule_r5_exports(root)
        cases.append(("R5-no-all", any(item.rule == "R5" for item in r5), f"{[item.render() for item in r5]}"))
        (bare / "__init__.py").write_text('__all__ = ["x"]\n', encoding="utf-8")
        _git_add(root)
        cases.append(("R5-clean", not rule_r5_exports(root), f"{[item.render() for item in rule_r5_exports(root)]}"))

        # R6: critical package needs a map whose key files exist.
        (package / "bootstrap/AGENTS.md").unlink()
        _git_add(root)
        r6 = rule_r6_maps(root)
        cases.append(
            (
                "R6-missing-map",
                any("bootstrap" in item.path and "AGENTS.md" in item.message for item in r6),
                f"{[item.render() for item in r6]}",
            )
        )
        (package / "bootstrap/AGENTS.md").write_text(
            "# map\n关键文件：`__init__.py`、`thing.py`\n", encoding="utf-8"
        )
        _git_add(root)
        cases.append(
            (
                "R6-clean-for-bootstrap",
                not any(item.path.startswith("src/questorharness/bootstrap") for item in rule_r6_maps(root)),
                f"{[item.render() for item in rule_r6_maps(root) if item.path.startswith('src/questorharness/bootstrap')]}",
            )
        )

        # R7: source without a mirror test.
        lonely = package / "lonely.py"
        lonely.write_text("VALUE = 1\n", encoding="utf-8")
        _git_add(root)
        r7 = rule_r7_mirror(root)
        cases.append(("R7-mirror-missing", any(item.rule == "R7" for item in r7), f"{[item.render() for item in r7]}"))
        lonely.unlink()

        # R8: cyclomatic complexity above 20.
        complex_file = package / "complex_mod.py"
        branches = "\n".join(f"    if x == {index}:\n        return {index}" for index in range(21))
        complex_file.write_text(f"def heavy(x):\n{branches}\n    return -1\n", encoding="utf-8")
        _git_add(root)
        r8, _ = rule_r8_complexity(root)
        cases.append(("R8-complexity", any(item.rule == "R8" for item in r8), f"{[item.render() for item in r8]}"))
        complex_file.write_text("def light(x):\n    return x\n", encoding="utf-8")
        _git_add(root)
        r8_clean, _ = rule_r8_complexity(root)
        cases.append(("R8-clean", not r8_clean, f"{[item.render() for item in r8_clean]}"))

    return run_self_test(cases)


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _git_init(root: Path) -> None:
    _git("init", "-q", cwd=root)
    _git("add", "-A", cwd=root)


def _git_add(root: Path) -> None:
    _git("add", "-A", cwd=root)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="prove every rule can go red")
    parser.add_argument(
        "--fail-on-empty",
        action="store_true",
        help="treat a missing scan target as a configuration error",
    )
    parser.add_argument("--root", default=str(REPO_ROOT), help="repository root to scan")
    parser.add_argument("--report", action="store_true", help="list every violation, including warnings")
    args = parser.parse_args(argv)
    if args.self_test:
        return _self_test()

    root = Path(args.root).resolve()
    try:
        if args.fail_on_empty:
            fail_on_empty("python sources", list(tracked_files(root, ("src",))))
        problems = collect_problems(root)
        violations, budget_problems = _violations(root)
    except GuardConfigError as exc:
        print(f"layout guard: config error: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    failures = [item for item in violations if item.severity == "fail"]
    warnings = [item for item in violations if item.severity == "warn"]

    if args.report or failures or problems or budget_problems:
        for warning in warnings:
            print(f"  warn {warning.render()}")
    if problems:
        print("layout guard: layout regressions found:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
    for failure in failures:
        print(f"layout guard: {failure.render()}", file=sys.stderr)
    for problem in budget_problems:
        print(f"layout guard: exemption budget: {problem}", file=sys.stderr)

    if problems or failures or budget_problems:
        return EXIT_RED

    counts = exemptions_by_rule(root)
    summary = ", ".join(f"{rule} {count}" for rule, count in counts.items()) or "none"
    print(
        "layout guard: OK (R1-R8 clean, phase 2 pins hold, "
        f"{len(warnings)} warning(s), inline exemptions: {summary})"
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
