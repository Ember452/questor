#!/usr/bin/env python3
"""R10: the namespace registries must be unique, real and complete.

Three assertions (plan 01, W2):

1. names are unique inside a namespace, case-insensitively;
2. every producer and consumer path registered in the document exists;
3. every name the code declares (tool, command, event, config key, env var,
   entry point, skill id) is registered — a missing row is red.

Extra: environment variables may only use the ``QUESTORHARNESS_`` prefix, and an
empty namespace is a failure, never a silent pass.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path

try:
    from ._guard_kit import EXIT_CONFIG, EXIT_OK, EXIT_RED, GuardConfigError, run_self_test
    from ._namespace_sources import (
        EMPTY_CELL,
        NAMESPACES,
        Row,
        collect_code_names,
        consumer_tokens,
        read_rows,
    )
except ImportError:  # direct script execution
    from _guard_kit import EXIT_CONFIG, EXIT_OK, EXIT_RED, GuardConfigError, run_self_test
    from _namespace_sources import (
        EMPTY_CELL,
        NAMESPACES,
        Row,
        collect_code_names,
        consumer_tokens,
        read_rows,
    )

REPO_ROOT = Path(__file__).resolve().parents[2]
TARGET = REPO_ROOT / "docs/architecture/NAMESPACES.md"
ENV_PREFIX = "QUESTORHARNESS_"


def _tokens(row: Row) -> list[str]:
    tokens = [token.strip("` ") for token in re.findall(r"`([^`]+)`", row.producer)]
    return [token for token in tokens if token and token != EMPTY_CELL]


def validate(
    rows: dict[str, list[Row]],
    code: dict[str, list[tuple[str, str]]],
    root: Path,
) -> list[str]:
    """Return every problem in the registry, given parsed rows and code names."""
    problems: list[str] = []

    for namespace in NAMESPACES:
        entries = rows.get(namespace, [])
        if not entries:
            problems.append(f"{namespace}: namespace is empty (registration is mandatory)")
            continue
        seen: dict[str, Row] = {}
        for row in entries:
            key = row.name.lower()
            if key in seen:
                problems.append(f"{namespace}: duplicate name '{row.name}' (also on line of '{seen[key].name}')")
                continue
            seen[key] = row
            paths = _tokens(row) + consumer_tokens(row.consumers)
            for token in paths:
                if not (root / token).exists():
                    problems.append(f"{namespace}/{row.name}: path does not exist: {token}")
            if namespace == "env" and not row.name.startswith(ENV_PREFIX):
                problems.append(f"env/{row.name}: must start with {ENV_PREFIX}")

    for namespace in NAMESPACES:
        registered = {row.name for row in rows.get(namespace, [])}
        for name, producer in code.get(namespace, []):
            if name not in registered:
                problems.append(f"{namespace}: code declares '{name}' ({producer}) but it is not registered")
    return problems


def _self_test() -> int:
    """Three cases: duplicate, missing path, unregistered code name."""
    import tempfile

    cases: list[tuple[str, bool, str]] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "src").mkdir()
        (root / "src/thing.py").write_text("VALUE = 1\n", encoding="utf-8")

        def default_name(namespace: str) -> str:
            return "QUESTORHARNESS_ONE" if namespace == "env" else "one"

        def rows(**overrides: list[tuple[str, str, str]]) -> dict[str, list[Row]]:
            base = {
                namespace: [Row(namespace, default_name(namespace), "`src/thing.py`", "`src/thing.py`")]
                for namespace in NAMESPACES
            }
            for namespace, entries in overrides.items():
                base[namespace] = [Row(namespace, name, producer, consumers) for name, producer, consumers in entries]
            return base

        code = {namespace: [(default_name(namespace), "src/thing.py")] for namespace in NAMESPACES}

        clean = validate(rows(), code, root)
        cases.append(("clean-registry", clean == [], f"{clean}"))

        duplicate = validate(rows(tool=[("one", "`src/thing.py`", "`src/thing.py`"), ("ONE", "`src/thing.py`", "`src/thing.py`")]), code, root)
        cases.append(
            (
                "duplicate-name",
                any("duplicate name" in item for item in duplicate),
                f"{duplicate}",
            )
        )

        missing = validate(rows(tool=[("one", "`src/missing.py`", "`src/thing.py`")]), code, root)
        cases.append(
            (
                "missing-path",
                any("path does not exist" in item for item in missing),
                f"{missing}",
            )
        )

        unregistered = validate(
            rows(tool=[]),
            {
                "tool": [("ghost", "src/thing.py")],
                **{name: [] for name in NAMESPACES if name != "tool"},
            },
            root,
        )
        cases.append(
            (
                "unregistered-name",
                any("is not registered" in item for item in unregistered),
                f"{unregistered}",
            )
        )
    return run_self_test(cases)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="prove the three assertions can go red")
    parser.add_argument(
        "--fail-on-empty",
        action="store_true",
        help="treat a missing document or empty namespace as a configuration error",
    )
    parser.add_argument("--target", default=str(TARGET), help="namespace document to read")
    args = parser.parse_args(argv)
    if args.self_test:
        return _self_test()

    target = Path(args.target)
    if not target.exists():
        print(f"name registries: missing document: {target}", file=sys.stderr)
        return EXIT_CONFIG

    try:
        rows = read_rows(target)
        code = collect_code_names(REPO_ROOT)
    except GuardConfigError as exc:
        print(f"name registries: config error: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    if args.fail_on_empty:
        empty = [namespace for namespace in NAMESPACES if not rows.get(namespace)]
        if empty or sum(len(items) for items in rows.values()) == 0:
            print(f"name registries: config error: empty namespace(s): {empty}", file=sys.stderr)
            return EXIT_CONFIG

    problems = validate(rows, code, REPO_ROOT)
    if problems:
        print("name registries: registration gaps found:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return EXIT_RED

    total = sum(len(items) for items in rows.values())
    summary = ", ".join(f"{namespace} {len(rows[namespace])}" for namespace in NAMESPACES)
    print(f"name registries: OK ({total} names registered; {summary})")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
