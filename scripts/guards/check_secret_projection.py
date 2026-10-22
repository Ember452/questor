#!/usr/bin/env python3
"""Prevent credential values from reaching logs or event payloads."""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

try:
    from ._guard_kit import (
        EXIT_CONFIG,
        EXIT_OK,
        EXIT_RED,
        GuardConfigError,
        fail_on_empty,
        read_text,
        run_self_test,
        walk_py,
    )
except ImportError:  # direct script execution
    from _guard_kit import (
        EXIT_CONFIG,
        EXIT_OK,
        EXIT_RED,
        GuardConfigError,
        fail_on_empty,
        read_text,
        run_self_test,
        walk_py,
    )

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TARGETS = (ROOT / "src" / "questorharness", ROOT / "src" / "questor")
SECRET_NAME_RE = re.compile(
    r"(^|_)(api_?key|access_?key|client_secret|secret|token|access_token|refresh_token|"
    r"auth_token|password|credential|credentials|authorization|private_?key|full_?args|"
    r"raw_?args|env_?values|environment)$",
    re.IGNORECASE,
)
EVENT_CALLS = frozenset({"InboundMessage", "OutboundMessage", "Envelope", "Event"})
LOG_METHODS = frozenset({"debug", "info", "warning", "warn", "error", "exception", "critical", "log"})


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    message: str


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _is_secret(name: str) -> bool:
    return bool(name and SECRET_NAME_RE.search(name))


def _dict_keys(node: ast.AST) -> list[str]:
    keys: list[str] = []
    if isinstance(node, ast.Dict):
        for key in node.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                keys.append(key.value)
    elif isinstance(node, ast.Call) and _call_name(node.func) == "dict":
        for keyword in node.keywords:
            if keyword.arg:
                keys.append(keyword.arg)
    return keys


def _secret_nodes(node: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and _is_secret(child.id):
            found.append((child.lineno, child.id))
        elif isinstance(child, ast.Attribute) and _is_secret(child.attr):
            found.append((child.lineno, child.attr))
        elif isinstance(child, (ast.Dict, ast.Call)):
            for key in _dict_keys(child):
                if _is_secret(key):
                    found.append((getattr(child, "lineno", 1), key))
    return found


def scan_source(path: Path, text: str) -> tuple[list[Violation], int]:
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        return [Violation(path, exc.lineno or 1, f"syntax error: {exc.msg}")], 0

    violations: list[Violation] = []
    sites = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node.func)
        if name in EVENT_CALLS:
            sites += 1
            for keyword in node.keywords:
                if keyword.arg and _is_secret(keyword.arg):
                    violations.append(
                        Violation(path, keyword.value.lineno, f"secret-shaped event field: {keyword.arg}")
                    )
                for line, key in _secret_nodes(keyword.value):
                    violations.append(
                        Violation(path, line, f"secret-shaped key in event payload: {key}")
                    )
            for arg in node.args:
                for line, key in _secret_nodes(arg):
                    violations.append(Violation(path, line, f"secret-shaped key in event payload: {key}"))
        elif name in LOG_METHODS:
            sites += 1
            for keyword in node.keywords:
                if keyword.arg and _is_secret(keyword.arg):
                    violations.append(
                        Violation(path, keyword.value.lineno, f"secret-shaped log field: {keyword.arg}")
                    )
            for arg in list(node.args) + [keyword.value for keyword in node.keywords]:
                for line, key in _secret_nodes(arg):
                    violations.append(Violation(path, line, f"secret-shaped value in log call: {key}"))
    return violations, sites


def _self_test() -> int:
    red_source = """
import logging
logger = logging.getLogger(__name__)
logger.info("auth", api_key=key)
OutboundMessage(metadata={"token": access_token})
"""
    green_source = """
import logging
logger = logging.getLogger(__name__)
logger.info("auth ok")
OutboundMessage(metadata={"trace_id": trace_id})
"""
    red, red_sites = scan_source(Path("<red>"), red_source)
    green, green_sites = scan_source(Path("<green>"), green_source)
    cases = [
        ("red-log-key", any("log" in item.message for item in red), f"{len(red)} violations"),
        ("red-event-token", any("event payload" in item.message for item in red), f"{red_sites} sites"),
        ("green-clean", not green, f"{len(green)} violations"),
        ("sites-counted", red_sites > 0 and green_sites > 0, f"red={red_sites} green={green_sites}"),
    ]
    return run_self_test(cases)


def _scan(paths: Iterable[Path], *, fail_on_empty_scan: bool) -> int:
    files = [path for root in paths for path in walk_py(root)]
    if fail_on_empty_scan:
        try:
            fail_on_empty("python source files", files)
        except GuardConfigError as exc:
            print(f"secret-projection guard: config error: {exc}", file=sys.stderr)
            return EXIT_CONFIG

    violations: list[Violation] = []
    sites = 0
    for path in files:
        found, count = scan_source(path, read_text(path))
        violations.extend(found)
        sites += count
    if fail_on_empty_scan and sites == 0:
        print("secret-projection guard: config error: no log/event call sites found", file=sys.stderr)
        return EXIT_CONFIG

    for item in violations:
        print(f"{item.path}:{item.line}: {item.message}", file=sys.stderr)
    if violations:
        return EXIT_RED
    print(f"secret-projection guard: OK ({len(files)} files, {sites} log/event call sites)")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="prove the guard can go red and green")
    parser.add_argument(
        "--fail-on-empty",
        action="store_true",
        help="treat an empty file set or no log/event call sites as a configuration error",
    )
    parser.add_argument("--root", action="append", type=Path, default=[], help="additional source root")
    args = parser.parse_args(argv)
    if args.self_test:
        return _self_test()
    roots = tuple(args.root) or DEFAULT_TARGETS
    return _scan(roots, fail_on_empty_scan=args.fail_on_empty)


if __name__ == "__main__":
    raise SystemExit(main())
