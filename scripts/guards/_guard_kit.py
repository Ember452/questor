#!/usr/bin/env python3
"""Shared guard utilities: deterministic walking, text I/O, self-test output, and fail-on-empty."""

from __future__ import annotations

import argparse
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path

EXIT_OK = 0
EXIT_RED = 1
EXIT_CONFIG = 2

SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "__pycache__",
        "node_modules",
        "build",
        "dist",
        "docs-pre-reset-v1",
    }
)


class GuardConfigError(RuntimeError):
    """Raised when a guard is pointed at an empty or invalid target."""


def walk_py(root: str | Path) -> Iterable[Path]:
    """Yield sorted Python files under root, skipping generated/vendor directories."""
    base = Path(root)
    if not base.exists():
        raise GuardConfigError(f"scan root does not exist: {base}")
    for path in sorted(base.rglob("*.py")):
        if SKIP_DIRS.intersection(path.parts):
            continue
        yield path


def read_text(path: str | Path) -> str:
    """Read UTF-8 text, accepting and stripping a BOM."""
    return Path(path).read_text(encoding="utf-8-sig")


def count_lines(path: str | Path) -> int:
    """Count lines with the same semantics as ``len(text.splitlines())``."""
    return len(read_text(path).splitlines())


def fail_on_empty(name: str, items: Sequence[object] | Iterable[object]) -> None:
    """Treat an empty scan set as a configuration error, not a pass."""
    values = list(items)
    if not values:
        raise GuardConfigError(f"empty scan target: {name}")
    return None


def run_self_test(cases: Sequence[tuple[str, bool, str]]) -> int:
    """Print a uniform self-test report and return a guard exit code."""
    failed = 0
    for label, ok, detail in cases:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {label}: {detail}")
        if not ok:
            failed += 1
    print(f"self-test: {'PASS' if failed == 0 else 'FAIL'}")
    return EXIT_OK if failed == 0 else EXIT_RED


def _self_test() -> int:
    cases: list[tuple[str, bool, str]] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "pkg").mkdir()
        (root / "pkg" / "b.py").write_text("print('b')\n", encoding="utf-8")
        (root / "pkg" / "a.py").write_text("\ufeffprint('a')\nprint('a2')\n", encoding="utf-8")
        (root / ".venv").mkdir()
        (root / ".venv" / "ignored.py").write_text("print('ignored')\n", encoding="utf-8")

        files = list(walk_py(root))
        cases.append(
            (
                "walk-sorted-skips-generated",
                [path.name for path in files] == ["a.py", "b.py"],
                f"{[path.name for path in files]}",
            )
        )
        cases.append(
            (
                "read-bom-and-count-lines",
                count_lines(root / "pkg" / "a.py") == 2,
                f"lines={count_lines(root / 'pkg' / 'a.py')}",
            )
        )
        try:
            fail_on_empty("synthetic", [])
        except GuardConfigError:
            empty_rejected = True
        else:
            empty_rejected = False
        cases.append(("fail-on-empty", empty_rejected, "empty scan raises GuardConfigError"))
        try:
            fail_on_empty("synthetic", [1])
        except GuardConfigError:
            nonempty_rejected = False
        else:
            nonempty_rejected = True
        cases.append(("non-empty-passes", nonempty_rejected, "non-empty scan is accepted"))
    return run_self_test(cases)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="prove the kit can go red and green")
    args = parser.parse_args(argv)
    if not args.self_test:
        parser.print_help()
        return EXIT_CONFIG
    return _self_test()


if __name__ == "__main__":
    raise SystemExit(main())
