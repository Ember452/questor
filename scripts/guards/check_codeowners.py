#!/usr/bin/env python3
"""Keep .github/CODEOWNERS real (plan 01, W10).

GitHub accepts a CODEOWNERS file that names nobody: an unrecognised handle does
not fail a PR, it just silently requests no review. So ownership is checked the
way the other structural facts are:

* every first-level source domain that contains Python files must be covered;
* every owner must be one of the confirmed handles (a guessed handle is a defect,
  not a placeholder);
* no TODO/FIXME/placeholder text may stand in for an owner;
* a rule whose path no longer exists is reported, so the file cannot accrete
  ownership of deleted code.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

try:
    from ._guard_kit import EXIT_CONFIG, EXIT_OK, EXIT_RED, read_text, run_self_test, tracked_files
except ImportError:  # direct script execution
    from _guard_kit import EXIT_CONFIG, EXIT_OK, EXIT_RED, read_text, run_self_test, tracked_files

REPO_ROOT = Path(__file__).resolve().parents[2]
CODEOWNERS = ".github/CODEOWNERS"

# Confirmed GitHub handles. peppa-web is a contributor but the handle was never
# verified, so nothing may be assigned to them until it is confirmed (plan 01 W10).
ALLOWED_OWNERS = frozenset({"@Ember452"})
PLACEHOLDER_TOKENS = ("TODO", "FIXME", "TBD", "owner?", "@<", "@owner")


def _rules(text: str) -> list[tuple[int, str, list[str]]]:
    rules: list[tuple[int, str, list[str]]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) < 2:
            rules.append((number, parts[0], []))
            continue
        rules.append((number, parts[0], parts[1:]))
    return rules


def source_domains(root: Path) -> list[str]:
    """First-level domains under ``src`` that contain Python files."""

    found: set[str] = set()
    for path in tracked_files(root, ("src",)):
        if path.suffix != ".py":
            continue
        parts = path.relative_to(root).parts
        if len(parts) >= 3 and parts[0] == "src" and parts[1] == "questorharness":
            if parts[2].endswith(".py"):
                continue
            found.add("/".join(parts[:3]))
        elif len(parts) >= 2 and parts[0] == "src":
            if parts[1].endswith(".py"):
                continue
            found.add("/".join(parts[:2]))
    return sorted(found)


def collect(root: Path) -> list[str]:
    """Return every CODEOWNERS problem for a repository root."""

    target = root / CODEOWNERS
    if not target.exists():
        return [f"{CODEOWNERS} is missing"]
    rules = _rules(read_text(target))
    if not rules:
        return [f"{CODEOWNERS} declares no rules"]

    problems: list[str] = []
    covered: list[str] = []
    has_catch_all = False
    for number, pattern, owners in rules:
        for owner in owners:
            if owner not in ALLOWED_OWNERS:
                problems.append(f"{CODEOWNERS}:{number} unconfirmed owner {owner!r} for {pattern}")
        if not owners:
            problems.append(f"{CODEOWNERS}:{number} pattern {pattern} has no owner")
        for token in (pattern, *owners):
            if any(bad in token for bad in PLACEHOLDER_TOKENS):
                problems.append(f"{CODEOWNERS}:{number} placeholder text: {token!r}")
        if pattern == "*":
            has_catch_all = True
            continue
        if "*" in pattern or "?" in pattern:
            # A glob rule cannot be checked for existence and does not name a
            # directory, so it neither proves nor disproves domain coverage.
            continue
        if pattern.startswith("/src/"):
            relative = pattern.strip("/").rstrip("/")
            if not (root / relative).exists():
                problems.append(f"{CODEOWNERS}:{number} path no longer exists: {pattern}")
            covered.append(relative)

    # Domain coverage is demanded explicitly: a catch-all makes the file valid to
    # GitHub, but it says nothing about who owns which domain (plan 01 W10).
    for domain in source_domains(root):
        if any(domain == entry or domain.startswith(entry + "/") for entry in covered):
            continue
        problems.append(f"{CODEOWNERS}: source domain {domain} has no explicit rule")
    if not has_catch_all:
        problems.append(f"{CODEOWNERS}: no catch-all rule for paths outside src/")
    return problems


def _self_test() -> int:
    import tempfile

    cases: list[tuple[str, bool, str]] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".github").mkdir()
        (root / "src" / "questorharness" / "engine").mkdir(parents=True)
        (root / "src" / "questorharness" / "engine" / "query.py").write_text("VALUE = 1\n", encoding="utf-8")
        # source_domains reads the index, so the fixture has to be a repository.
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        owners = root / ".github" / "CODEOWNERS"
        owners.write_text("* @Ember452\n/src/questorharness/engine/ @Ember452\n", encoding="utf-8")
        cases.append(("clean", collect(root) == [], f"{collect(root)}"))

        owners.write_text("* @Ember452\n", encoding="utf-8")
        problems = collect(root)
        cases.append(
            ("catch-all-alone-is-not-domain-coverage", any("no explicit rule" in item for item in problems), f"{problems}")
        )

        owners.write_text("* @someone-else\n", encoding="utf-8")
        problems = collect(root)
        cases.append(("unconfirmed-owner-flagged", any("unconfirmed owner" in item for item in problems), f"{problems}"))

        owners.write_text("/src/questorharness/engine/ @Ember452\n", encoding="utf-8")
        problems = collect(root)
        cases.append(("missing-catch-all-flagged", any("no catch-all" in item for item in problems), f"{problems}"))

        owners.write_text("* @Ember452\n/src/gone/domain/ @Ember452\n", encoding="utf-8")
        problems = collect(root)
        cases.append(
            ("stale-path-flagged", any("no longer exists" in item for item in problems), f"{problems}")
        )

        owners.write_text("* TODO(owner)\n", encoding="utf-8")
        problems = collect(root)
        cases.append(("placeholder-flagged", any("placeholder" in item for item in problems), f"{problems}"))

        (root / ".github" / "CODEOWNERS").unlink()
        cases.append(("missing-file", collect(root) != [], f"{collect(root)}"))
    return run_self_test(cases)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="prove each rule can go red")
    parser.add_argument("--fail-on-empty", action="store_true", help="a file with no rules is a config error")
    parser.add_argument("--root", default=str(REPO_ROOT), help="repository root to scan")
    args = parser.parse_args(argv)
    if args.self_test:
        return _self_test()

    root = Path(args.root).resolve()
    rules = _rules(read_text(root / CODEOWNERS)) if (root / CODEOWNERS).exists() else []
    if args.fail_on_empty and not rules:
        print("codeowners guard: config error: no rules declared", file=sys.stderr)
        return EXIT_CONFIG

    problems = collect(root)
    if problems:
        print("codeowners guard: ownership drift found:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return EXIT_RED
    print(f"codeowners guard: OK ({len(rules)} rules, {len(source_domains(root))} source domains covered)")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
