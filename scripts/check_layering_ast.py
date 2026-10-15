#!/usr/bin/env python3
"""Mechanical layering guard (HARD-CONSTRAINTS C1/C14/C15; STRUCTURE §9).

import-linter only sees static ``import`` statements and has zero adoption in
the reference repos (R09). This checker adds the missing defense: it flags
*dynamic* imports (``importlib.import_module`` / ``__import__``) that point a
lower layer at an outer layer, and it fails on an empty scan (no files found =
misconfiguration, not a pass).

Usage:
    uv run python scripts/check_layering_ast.py            # scan src/questor
    uv run python scripts/check_layering_ast.py --self-test  # prove it can go red
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

# L0 innermost → L6 outermost. A module may import its own layer or a LOWER
# (more inner) one; importing a HIGHER (more outer) layer is a violation.
LAYER_RANK: dict[str, int] = {
    "contracts": 0,
    "state": 1,
    "kernel": 2,
    "capabilities": 3,
    "policy": 4,
    "providers": 5,
    "surfaces": 6,
    "config": 7,
    "observability": 7,
}
_ROOT_PKG = "questor"


def _layer_of(module: str) -> str | None:
    """Return the questor sub-layer owning ``module`` (e.g. 'questor.kernel.x')."""
    parts = module.split(".")
    if len(parts) >= 2 and parts[0] == _ROOT_PKG:
        return parts[1] if parts[1] in LAYER_RANK else None
    return None


def _referenced_layers(node: ast.AST) -> list[tuple[int, str]]:
    """Yield (lineno, imported questor sub-layer) for a node, incl. dynamic ones."""
    found: list[tuple[int, str]] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Import):
            for alias in child.names:
                layer = _layer_of(alias.name)
                if layer:
                    found.append((child.lineno, layer))
        elif isinstance(child, ast.ImportFrom) and child.module:
            if child.level:  # relative import — normalized elsewhere; skip
                continue
            layer = _layer_of(child.module)
            if layer:
                found.append((child.lineno, layer))
        elif isinstance(child, ast.Call):
            func = child.func
            dyn = (isinstance(func, ast.Attribute) and func.attr == "import_module") or (
                isinstance(func, ast.Name) and func.id == "__import__"
            )
            if dyn and child.args and isinstance(child.args[0], ast.Constant):
                arg = child.args[0].value
                if isinstance(arg, str):
                    layer = _layer_of(arg)
                    if layer:
                        found.append((child.lineno, layer))
    return found


def analyze_source(source: str, own_layer: str, path: str = "<string>") -> list[str]:
    """Return violation messages for imports of an OUTER layer from ``own_layer``."""
    tree = ast.parse(source)
    violations: list[str] = []
    own_rank = LAYER_RANK.get(own_layer, -1)
    for lineno, imported in _referenced_layers(tree):
        if LAYER_RANK.get(imported, -1) > own_rank:
            violations.append(
                f"{path}:{lineno}: layer '{own_layer}' must not import outer "
                f"layer '{imported}' (C1/C14)"
            )
    return violations


def check(root: Path) -> tuple[list[str], int]:
    """Scan every module under ``root``; return (violations, files_scanned)."""
    violations: list[str] = []
    scanned = 0
    for py in sorted(root.rglob("*.py")):
        module_layers = [p for p in py.parts if p in LAYER_RANK]
        if not module_layers:
            continue
        scanned += 1
        violations += analyze_source(py.read_text(encoding="utf-8"), module_layers[-1], str(py))
    return violations, scanned


def self_test() -> int:
    """Prove the guard flags a bad dynamic import and passes a good one."""
    bad = 'import importlib\nimportlib.import_module("questor.surfaces")\n'
    good = "from questor.contracts import events\n"
    bad_hits = analyze_source(bad, "kernel")
    good_hits = analyze_source(good, "kernel")
    ok = bool(bad_hits) and not good_hits
    print(f"self-test: bad-import flagged={bool(bad_hits)} clean-passed={not good_hits}")
    for msg in bad_hits:
        print(f"  expected-red -> {msg}")
    print("self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="run built-in fixtures")
    parser.add_argument("--root", default="src/questor", type=Path)
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    violations, scanned = check(args.root)
    if scanned == 0:
        print(f"fail-on-empty: scanned 0 modules under {args.root}", file=sys.stderr)
        return 2
    for msg in violations:
        print(msg)
    print(f"layering AST: {scanned} files scanned, {len(violations)} violation(s)")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
