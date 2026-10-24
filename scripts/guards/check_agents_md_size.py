#!/usr/bin/env python3
"""Keep the root AGENTS.md a signpost, not a handbook (plan 01, W7).

The rulebook moved verbatim into ``docs/CONVENTIONS.md``; this cap exists because
line count alone can be gamed by unwrapping prose. Over 170 lines or over 16 KiB
means content came back instead of being linked.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

try:
    from ._guard_kit import EXIT_OK, EXIT_RED, count_lines, read_text, run_self_test
except ImportError:  # direct script execution
    from _guard_kit import EXIT_OK, EXIT_RED, count_lines, read_text, run_self_test

REPO_ROOT = Path(__file__).resolve().parents[2]
MAX_LINES = 170
MAX_BYTES = 16 * 1024


def check(root: Path) -> list[str]:
    """Return every size problem for the root AGENTS.md."""

    target = root / "AGENTS.md"
    if not target.exists():
        return ["AGENTS.md is missing at the repository root"]
    lines = count_lines(target)
    size = len(read_text(target).encode("utf-8"))
    problems: list[str] = []
    if lines > MAX_LINES:
        problems.append(f"root AGENTS.md is {lines} lines > {MAX_LINES}; move prose to docs/CONVENTIONS.md")
    if size > MAX_BYTES:
        problems.append(f"root AGENTS.md is {size} bytes > {MAX_BYTES}; move prose to docs/CONVENTIONS.md")
    return problems


def _self_test() -> int:
    import tempfile

    cases: list[tuple[str, bool, str]] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "AGENTS.md").write_text("# rules\n", encoding="utf-8")
        cases.append(("clean", check(root) == [], f"{check(root)}"))
        (root / "AGENTS.md").write_text(
            "\n".join(f"line {index}" for index in range(MAX_LINES + 1)) + "\n", encoding="utf-8"
        )
        problems = check(root)
        cases.append(("too-many-lines", any("lines >" in item for item in problems), f"{problems}"[:150]))
        (root / "AGENTS.md").write_text("# pad\n" + ("x" * (MAX_BYTES + 10)) + "\n", encoding="utf-8")
        problems = check(root)
        cases.append(("too-many-bytes", any("bytes >" in item for item in problems), f"{problems}"[:150]))
        (root / "AGENTS.md").unlink()
        cases.append(("missing-file", check(root) != [], f"{check(root)}"))
    return run_self_test(cases)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="prove the size gate can go red")
    parser.add_argument("--root", default=str(REPO_ROOT), help="repository root to scan")
    args = parser.parse_args(argv)
    if args.self_test:
        return _self_test()

    root = Path(args.root).resolve()
    problems = check(root)
    if problems:
        print("agents size guard: root AGENTS.md out of budget", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return EXIT_RED
    target = root / "AGENTS.md"
    print(
        f"agents size guard: OK (root AGENTS.md {count_lines(target)} lines / "
        f"{len(read_text(target).encode('utf-8'))} bytes)"
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
