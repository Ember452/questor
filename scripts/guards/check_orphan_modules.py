#!/usr/bin/env python3
"""Report modules nothing imports (plan 01, W10).

An orphan is a source module that no other source module imports, no test
references, is not a ``__main__`` entry point and is not named by a
``[project.scripts]`` target. The guard reports only by default: the first pass is
evidence, and ``--blocking`` turns it red once the list has been reviewed. Per the
plan, a share above ``--max-percent`` is the point where blocking becomes fair.

Why it matters: an unimported module still costs reading time, still shows up in
the tree map, and still gets patched around by later work. Either it is dead, or
it is an entry point nobody documented - both are worth naming out loud.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Sequence
from pathlib import Path

try:
    from ._guard_kit import EXIT_CONFIG, EXIT_OK, EXIT_RED, read_text, run_self_test, tracked_files
except ImportError:  # direct script execution
    from _guard_kit import EXIT_CONFIG, EXIT_OK, EXIT_RED, read_text, run_self_test, tracked_files

REPO_ROOT = Path(__file__).resolve().parents[2]
MAX_PERCENT_DEFAULT = 5.0

# Packages loaded by walking, where nobody writes an import statement: every
# module under these roots is reached at runtime, so calling it orphaned would be
# the false alarm the plan warns about. Adding a root here needs the walker that
# justifies it; removing one is what the report is for.
DISCOVERY_ROOTS = (
    # capabilities/tools/registry.py walks the package with pkgutil and resolves
    # every BaseTool subclass it finds.
    "questorharness.capabilities.tools",
)


def dotted(relative: Path) -> str:
    """Module dotted name, with the ``src`` layout directory removed.

    Imports never mention ``src`` (it is a layout root, not a package), so keeping
    it here would make every module look unimported.
    """

    parts = list(relative.with_suffix("").parts)
    if parts and parts[0] == "src":
        parts.pop(0)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def entry_point_modules(root: Path) -> set[str]:
    """Modules named by any console script or entry-point group.

    ``[project.entry-points.<group>]`` matters as much as ``[project.scripts]``:
    questor-feishu = "questor.gateway.notify:register_handlers" is how a plugin
    reaches its module, and missing it reports live code as dead.
    """

    try:
        data = __import__("tomllib").loads(read_text(root / "pyproject.toml"))
    except (OSError, ValueError):
        return set()
    found: set[str] = set()
    project = data.get("project", {})
    tables: list[dict[str, object]] = []
    for key in ("scripts", "gui-scripts"):
        tables.append(project.get(key) or {})
    entry_points = project.get("entry-points") or {}
    if isinstance(entry_points, dict):
        for value in entry_points.values():
            if isinstance(value, dict):
                tables.append(value)
    for table in tables:
        for target in table.values():
            module = str(target).split(":")[0].strip()
            if module:
                found.add(module)
    return found


def referenced_names(root: Path, scopes: tuple[str, ...] = ("src", "tests")) -> set[str]:
    """Every dotted name an import statement in ``scopes`` can resolve to.

    Relative imports are resolved against the importing module's package: skipping
    them would report a sibling-loaded module as orphaned, which is a false alarm
    that would train people to ignore the guard.
    """

    used: set[str] = set()
    for scope in scopes:
        for path in tracked_files(root, (scope,)):
            if path.suffix != ".py":
                continue
            try:
                tree = ast.parse(read_text(path))
            except (SyntaxError, UnicodeDecodeError):
                continue
            own = dotted(path.relative_to(root)).split(".")
            # ``from . import x`` resolves against the containing package: for a
            # plain module that means dropping its own name, for an __init__ it
            # means keeping the package it belongs to.
            own_parts = own if path.name == "__init__.py" else own[:-1]
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    used.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    used.add(node.module)
                    used.update(f"{node.module}.{alias.name}" for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level:
                    # ``from . import x`` inside a.b.c resolves against a.b (or a.b.c
                    # when the importer is an __init__).
                    base = ".".join(own_parts[: len(own_parts) - (node.level - 1)])
                    prefix = f"{base}." if base else ""
                    if node.module:
                        target = f"{prefix}{node.module}"
                        used.add(target)
                        used.update(f"{target}.{alias.name}" for alias in node.names)
                    else:
                        used.update(f"{prefix}{alias.name}" for alias in node.names)
    return used


def collect(root: Path) -> tuple[list[str], int]:
    """Return (orphan module paths, number of candidate modules)."""

    sources = [path for path in tracked_files(root, ("src",)) if path.suffix == ".py"]
    used = referenced_names(root)
    entries = entry_point_modules(root)
    orphans: list[str] = []
    candidates = 0
    for path in sources:
        relative = path.relative_to(root)
        name = dotted(relative)
        if not name or relative.name == "__init__.py" or not (root / relative).exists():
            continue
        candidates += 1
        if name.endswith("__main__") or name in entries:
            continue
        if any(name == prefix or name.startswith(prefix + ".") for prefix in DISCOVERY_ROOTS):
            continue
        if name in used:
            continue
        orphans.append(relative.as_posix())
    return sorted(orphans), candidates


def _self_test() -> int:
    import tempfile

    cases: list[tuple[str, bool, str]] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pkg = root / "src" / "demo"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "used.py").write_text("VALUE = 1\n", encoding="utf-8")
        (pkg / "lonely.py").write_text("VALUE = 1\n", encoding="utf-8")
        (pkg / "cli.py").write_text("app = 1\n", encoding="utf-8")
        (pkg / "runner.py").write_text("from demo.used import VALUE\n", encoding="utf-8")
        (pkg / "relative.py").write_text("from . import used\n", encoding="utf-8")
        deep = pkg / "deep"
        deep.mkdir()
        (deep / "__init__.py").write_text("from . import only_reached_by_relative_import\n", encoding="utf-8")
        (deep / "only_reached_by_relative_import.py").write_text("VALUE = 1\n", encoding="utf-8")
        (pkg / "__main__.py").write_text("from demo.cli import app\n", encoding="utf-8")
        tests = root / "tests"
        tests.mkdir()
        (tests / "test_tested.py").write_text("import demo.used\n", encoding="utf-8")
        (root / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
        import subprocess

        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        orphans, candidates = collect(root)
        cases.append(
            (
                "finds-unimported-modules",
                orphans == ["src/demo/lonely.py", "src/demo/relative.py", "src/demo/runner.py"],
                f"{orphans}",
            )
        )
        cases.append(("counts-candidates", candidates >= 3, f"{candidates}"))
        normalised = orphans
        cases.append(
            (
                "relative-import-reaches-its-target",
                "src/demo/deep/only_reached_by_relative_import.py" not in normalised,
                f"{normalised}",
            )
        )
        (root / "pyproject.toml").write_text(
            '[project]\nname = "demo"\n\n[project.entry-points."demo.plugins"]\n'
            'demo = "demo.plugin:register"\n',
            encoding="utf-8",
        )
        (pkg / "plugin.py").write_text("register = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        after = collect(root)[0]
        cases.append(
            (
                "entry-point-group-is-not-orphan",
                "src/demo/plugin.py" not in after and "src/demo/cli.py" not in after,
                f"{after}",
            )
        )
    return run_self_test(cases)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="prove the detector sees an orphan")
    parser.add_argument("--fail-on-empty", action="store_true", help="no candidates is a configuration error")
    parser.add_argument("--blocking", action="store_true", help="exit red when any orphan remains")
    parser.add_argument("--max-percent", type=float, default=MAX_PERCENT_DEFAULT, help="share that justifies blocking")
    parser.add_argument("--root", default=str(REPO_ROOT), help="repository root to scan")
    args = parser.parse_args(argv)
    if args.self_test:
        return _self_test()

    root = Path(args.root).resolve()
    sources = [path for path in tracked_files(root, ("src",)) if path.suffix == ".py"]
    if args.fail_on_empty and not sources:
        print("orphan guard: config error: no source files found", file=sys.stderr)
        return EXIT_CONFIG

    orphans, candidates = collect(root)
    entries = entry_point_modules(root)
    percent = (100.0 * len(orphans) / candidates) if candidates else 0.0
    for item in orphans:
        print(f"orphan: {item}")
    print(
        f"orphan guard: {len(orphans)} of {candidates} modules unimported ({percent:.1f}%); "
        f"{'blocking' if args.blocking else 'report-only'} (threshold {args.max_percent:.1f}%, "
        f"{len(entries)} entry-point modules and {len(DISCOVERY_ROOTS)} discovery roots excluded)"
    )
    if args.blocking and (orphans or percent > args.max_percent):
        return EXIT_RED
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
