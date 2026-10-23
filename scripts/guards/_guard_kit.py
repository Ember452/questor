#!/usr/bin/env python3
"""Shared guard utilities: deterministic walking, text I/O, self-test output, and fail-on-empty."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

EXIT_OK = 0
EXIT_RED = 1
EXIT_CONFIG = 2


def _force_utf8_streams() -> None:
    """Print diffs on Windows consoles without dying on a non-GBK character.

    Guards report Chinese evidence and box-drawing symbols; a cp936 console made
    ``print`` raise UnicodeEncodeError and hide the very diff the developer needs
    (seen live in prompt_surface --check). Output is still bytes on the wire, so
    the parent runner keeps decoding UTF-8 regardless.
    """

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):  # already replaced or not a terminal stream
                pass


_force_utf8_streams()

EXEMPTION_RE = re.compile(r"#\s*questor:\s*allow\s+(R\d+)\s*--\s*(.+?)\s*$")
EXEMPTION_REASON_RE = re.compile(r"(until|when|W\d+)", re.IGNORECASE)

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


@dataclass(frozen=True)
class Exemption:
    """One ``# questor: allow <RULE> -- <reason>`` comment."""

    rule: str
    reason: str
    line: int


def tracked_files(
    root: str | Path,
    pathspecs: Sequence[str] = ("src",),
    suffixes: Sequence[str] = (".py",),
) -> list[Path]:
    """Return tracked files matching ``pathspecs``, resolved against ``root``.

    ``git ls-files`` is the single scanning caliber: untracked scratch output
    (``__pycache__``, ``.tmp-baseline``) can never make a guard report on files
    that are not part of the repository.
    """
    base = Path(root)
    result = subprocess.run(
        ["git", "ls-files", "--", *pathspecs],
        cwd=base,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise GuardConfigError(f"git ls-files failed under {base}: {result.stderr.strip()[:200]}")
    names = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and line.strip().endswith(tuple(suffixes))
    ]
    return sorted(base / name for name in names)


def parse_exemptions(path: str | Path, *, rule: str | None = None) -> dict[str, Exemption]:
    """Parse questor exemptions from one file.

    A comment without ``--`` or with an empty reason is not an exemption; the
    reason must name a wave (``until W8``) so every exemption has a deletion
    condition. Malformed lines are reported by ``exemption_errors`` instead of
    silently passing.
    """
    found: dict[str, Exemption] = {}
    for number, line in enumerate(read_text(path).splitlines(), start=1):
        if "questor:" not in line or "allow" not in line:
            continue
        match = EXEMPTION_RE.search(line)
        if match is None:
            continue
        name, reason = match.group(1), match.group(2).strip()
        if rule is not None and name != rule:
            continue
        if name in found:
            continue
        found[name] = Exemption(rule=name, reason=reason, line=number)
    return found


def exemption_errors(path: str | Path, text: str | None = None) -> list[str]:
    """Return problems with the exemption comments in one file."""
    body = read_text(path) if text is None else text
    problems: list[str] = []
    for number, line in enumerate(body.splitlines(), start=1):
        if "questor:" not in line or "allow" not in line:
            continue
        match = EXEMPTION_RE.search(line)
        if match is None:
            problems.append(f"line {number}: malformed exemption (need '# questor: allow <RULE> -- <reason>')")
            continue
        if not EXEMPTION_REASON_RE.search(match.group(2)):
            problems.append(
                f"line {number}: exemption reason must name a wave (until W8 / when ... / W9)"
            )
    return problems


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
