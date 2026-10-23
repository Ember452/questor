#!/usr/bin/env python3
"""Keep the Phase 2 layout from regressing.

Each rule below pins a decision that cost a migration wave to make; without a
guard the next change silently reintroduces the old shape:

* removed top-level packages stay removed (``ui/``, ``personalization/``);
* ``surfaces/`` holds renderer-facing adapters only, never process hosts;
* ``commands/registry.py`` stays an orchestrator, not a god file;
* command families stay under the file budget;
* the dropped UI toolkits do not come back through an import.
"""

from __future__ import annotations

import argparse
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
        walk_py,
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
        walk_py,
    )

REPO_ROOT = Path(__file__).resolve().parents[2]

REMOVED_PACKAGES = (
    "src/questorharness/ui",
    "src/questorharness/personalization",
    "src/questorharness/surfaces/ipc",
)
ALLOWED_SURFACES = {"channels"}
# ADR-0003 red line: any source file above this is a god file.
GLOBAL_LINE_BUDGET = 1200
FILE_BUDGETS = {"src/questorharness/commands/registry.py": 250}
DIR_BUDGETS = {"src/questorharness/commands/families": 600}
DROPPED_UI_IMPORTS = ("textual", "prompt_toolkit")


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

    # Global ADR-0003 red line: no source file may exceed 1200 lines.
    for path in walk_py(root / "src"):
        lines = count_lines(path)
        if lines > GLOBAL_LINE_BUDGET:
            problems.append(f"{_rel(path, root)}: {lines} lines > {GLOBAL_LINE_BUDGET}")
    return problems


def collect_problems(root: Path) -> list[str]:
    problems = [
        *(f"removed package came back: {name}" for name in find_removed_packages(root)),
        *(f"unexpected package under surfaces/: {name}" for name in find_unexpected_surfaces(root)),
        *(f"dropped UI toolkit imported: {hit}" for hit in find_dropped_ui_imports(root)),
        *find_oversized_files(root),
    ]
    return problems


def _self_test() -> int:
    cases: list[tuple[str, bool, str]] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pkg = root / "src/questorharness"
        (pkg / "surfaces/channels").mkdir(parents=True)
        (pkg / "commands/families").mkdir(parents=True)
        (pkg / "commands/registry.py").write_text("def x():\n    return 1\n", encoding="utf-8")
        (pkg / "commands/families/ok.py").write_text("VALUE = 1\n", encoding="utf-8")

        fresh = collect_problems(root)
        cases.append(("clean-tree-passes", fresh == [], f"{fresh}"))

        (pkg / "ui").mkdir()
        (pkg / "ui/app.py").write_text("VALUE = 1\n", encoding="utf-8")
        returned = find_removed_packages(root)
        cases.append(("removed-package-detected", returned == ["src/questorharness/ui"], f"{returned}"))
        (pkg / "ui/app.py").unlink()
        (pkg / "ui").rmdir()

        (pkg / "surfaces/ipc").mkdir()
        extra = find_unexpected_surfaces(root)
        cases.append(("surface-host-detected", extra == ["ipc"], f"{extra}"))
        (pkg / "surfaces/ipc").rmdir()

        (pkg / "surfaces/channels/textual_module.py").write_text(
            "from textual.app import App\n", encoding="utf-8"
        )
        dropped = find_dropped_ui_imports(root)
        cases.append(("dropped-toolkit-detected", len(dropped) == 1, f"{dropped}"))

        (pkg / "commands/registry.py").write_text("\n".join(["pass"] * 400) + "\n", encoding="utf-8")
        oversized = find_oversized_files(root)
        cases.append(("registry-budget-detected", any("registry.py" in item for item in oversized), f"{oversized}"))

    return run_self_test(cases)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="prove the guard can go red and green")
    parser.add_argument(
        "--fail-on-empty",
        action="store_true",
        help="treat a missing scan target as a configuration error",
    )
    parser.add_argument("--root", default=str(REPO_ROOT), help="repository root to scan")
    args = parser.parse_args(argv)
    if args.self_test:
        return _self_test()

    root = Path(args.root).resolve()
    try:
        if args.fail_on_empty:
            fail_on_empty("python sources", list(walk_py(root / "src")))
        problems = collect_problems(root)
    except GuardConfigError as exc:
        print(f"layout guard: config error: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    if problems:
        print("layout guard: layout regressions found:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return EXIT_RED

    print("layout guard: OK (removed packages stay gone, surfaces stay thin, file budgets hold)")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
