#!/usr/bin/env python3
"""Keep the mypy whitelist honest (plan 01, W4).

A whitelist alone decays: the checked set stays at 22 modules while the codebase
grows. Three rules stop that:

1. the whitelist roots in ``pyproject.toml`` may only grow, and the number of
   checked modules may only grow;
2. a package outside the whitelist may not gain modules — a new module has to
   join the whitelist or the pinned deferred count has to be raised in review;
3. ``# type: ignore`` inside the whitelist must carry a code and a reason, so
   "zero errors" cannot be bought with bare suppressions.

``tests/fixtures/baseline/mypy_deferred.json`` holds the pinned counts; it is a
package-level table (16 rows) rather than a module list (234 rows) so a human can
actually review a change to it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

try:
    from ._guard_kit import EXIT_CONFIG, EXIT_OK, EXIT_RED, read_text, run_self_test, tracked_files
except ImportError:  # direct script execution
    from _guard_kit import (
        EXIT_CONFIG,
        EXIT_OK,
        EXIT_RED,
        read_text,
        run_self_test,
        tracked_files,
    )

REPO_ROOT = Path(__file__).resolve().parents[2]
PINNED = REPO_ROOT / "tests/fixtures/baseline/mypy_deferred.json"
IGNORE_RE = re.compile(r"#\s*type:\s*ignore(?P<rest>.*)$")
BARE_REASON_RE = re.compile(r"^\[[a-z0-9_,\- ]+\]\s*(#|--)\s*\S+")


def _whitelist_roots() -> list[str]:
    data = tomllib.loads(read_text(REPO_ROOT / "pyproject.toml"))
    roots = data.get("tool", {}).get("mypy", {}).get("files", [])
    return [str(root).replace("\\", "/") for root in roots]


def _package_key(relative: str) -> str:
    parts = relative.split("/")
    if len(parts) > 3 and parts[1] == "questorharness":
        return "/".join(parts[:3])
    return "/".join(parts[:2])


def _is_inside(relative: str, root: str) -> bool:
    """A whitelist entry is either a package directory or one specific module.

    Treating every entry as a directory made a single-file root invisible: the
    module counted toward the deferred pool while the checked-file count stayed
    one short of what mypy actually reported.
    """

    return relative == root or relative.startswith(f"{root}/")


def _module_counts(roots: Sequence[str]) -> tuple[int, dict[str, int]]:
    inside = 0
    outside: Counter[str] = Counter()
    for path in tracked_files(REPO_ROOT, ("src",)):
        if path.name == "__init__.py":
            continue
        relative = path.relative_to(REPO_ROOT).as_posix()
        if any(_is_inside(relative, root) for root in roots):
            inside += 1
        else:
            outside[_package_key(relative)] += 1
    return inside, dict(sorted(outside.items()))


def _ignore_problems(roots: Sequence[str]) -> list[str]:
    problems: list[str] = []
    for path in tracked_files(REPO_ROOT, ("src",)):
        relative = path.relative_to(REPO_ROOT).as_posix()
        if not any(_is_inside(relative, root) for root in roots):
            continue
        for number, line in enumerate(read_text(path).splitlines(), start=1):
            if "type: ignore" not in line:
                continue
            match = IGNORE_RE.search(line)
            if match is None:
                continue
            rest = match.group("rest")
            if not rest.startswith("["):
                problems.append(f"{relative}:{number}: bare '# type: ignore' (add [code] and a reason)")
            elif not BARE_REASON_RE.match(rest):
                problems.append(f"{relative}:{number}: '# type: ignore[code]' needs a trailing reason")
    return problems


def compare(
    roots: Sequence[str],
    inside: int,
    outside: dict[str, int],
    pinned: dict[str, object],
) -> list[str]:
    """Return every scope problem, given the live counts and the pinned table."""
    problems: list[str] = []
    pinned_roots = list(pinned.get("whitelist_roots", []))
    missing = sorted(set(pinned_roots) - set(roots))
    added = sorted(set(roots) - set(pinned_roots))
    if missing:
        problems.append(f"whitelist roots removed: {', '.join(missing)} (only additions are allowed)")
    if added:
        problems.append(f"whitelist roots added: {', '.join(added)} (raise the pin in the same change)")

    pinned_modules = int(pinned.get("whitelist_modules", 0))  # type: ignore[arg-type]
    if inside < pinned_modules:
        problems.append(f"whitelisted modules dropped: {inside} < {pinned_modules}")

    pinned_packages = dict(pinned.get("packages", {}))  # type: ignore[arg-type]
    for package, count in sorted(outside.items()):
        allowed = int(pinned_packages.get(package, -1))
        if allowed < 0:
            problems.append(f"{package}: {count} modules outside the whitelist and not in the pin")
        elif count > allowed:
            problems.append(
                f"{package}: {count} modules > pinned {allowed} (add the module to mypy files or raise the pin)"
            )
    return problems


def _self_test() -> int:
    cases: list[tuple[str, bool, str]] = []
    roots = ["src/questorharness/contracts", "src/questorharness/platform"]
    pinned = {
        "whitelist_roots": list(roots),
        "whitelist_modules": 18,
        "packages": {"src/questorharness/capabilities": 81},
    }
    clean = compare(roots, 18, {"src/questorharness/capabilities": 81}, pinned)
    cases.append(("clean-scope", clean == [], f"{clean}"))

    dropped = compare(roots[:1], 18, {"src/questorharness/capabilities": 81}, pinned)
    cases.append(
        (
            "root-removed",
            any("whitelist roots removed" in item for item in dropped),
            f"{dropped}",
        )
    )

    grown = compare(roots, 18, {"src/questorharness/capabilities": 82}, pinned)
    cases.append(
        (
            "package-grew",
            any("82 modules > pinned 81" in item for item in grown),
            f"{grown}",
        )
    )

    unknown = compare(roots, 18, {"src/questorharness/engine": 9}, pinned)
    cases.append(
        (
            "unpinned-package",
            any("not in the pin" in item for item in unknown),
            f"{unknown}",
        )
    )
    return run_self_test(cases)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="prove the scope checks can go red")
    parser.add_argument(
        "--fail-on-empty",
        action="store_true",
        help="treat a missing pin or empty whitelist as a configuration error",
    )
    args = parser.parse_args(argv)
    if args.self_test:
        return _self_test()

    if not PINNED.exists():
        print(f"mypy scope: missing pin: {PINNED.relative_to(REPO_ROOT)}", file=sys.stderr)
        return EXIT_CONFIG

    roots = _whitelist_roots()
    if args.fail_on_empty and not roots:
        print("mypy scope: config error: empty whitelist", file=sys.stderr)
        return EXIT_CONFIG

    inside, outside = _module_counts(roots)
    if args.fail_on_empty and inside == 0:
        print("mypy scope: config error: whitelist matches no module", file=sys.stderr)
        return EXIT_CONFIG

    pinned = json.loads(PINNED.read_text(encoding="utf-8"))
    problems = compare(roots, inside, outside, pinned)
    problems.extend(_ignore_problems(roots))
    if problems:
        print("mypy scope: whitelist drift:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return EXIT_RED

    deferred = sum(outside.values())
    print(
        f"mypy scope: OK ({len(roots)} roots, {inside} modules checked, "
        f"{deferred} deferred across {len(outside)} packages)"
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
