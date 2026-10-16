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
#: Cross-cutting layers: any layer may import these (they depend only on
#: contracts and are read-only — STRUCTURE S7), so they never count as "outer".
CROSS_CUTTING: frozenset[str] = frozenset({"config", "observability"})
_ROOT_PKG = "questor"

#: 机械越权约束（T20）：某些能力必须根本不存在于某层，而不是靠"外层等级"间接挡。
#: 键是层名，值是禁止被 import 的模块前缀（stdlib 或 questor 具体实现）。
FORBIDDEN_IMPORTS: dict[str, tuple[str, ...]] = {
    # 工具绝不自己 spawn 进程 / 直接依赖沙箱具体实现（进程/env 都在 L5 ProcessRunner）。
    "capabilities": (
        "subprocess",
        "questor.providers.sandbox",
        "questor.providers.process_runner",
        "questor.providers._win_job",
    ),
    # surfaces 零业务：不碰 reduce、不碰 store 具体实现（经 Command Inbox / 注入 StorePort）。
    "surfaces": (
        "questor.state.reduce",
        "questor.providers.store_sqlite",
        "subprocess",
    ),
    # L0 词汇层只放数据与纯不变式，不碰 IO/网络/进程。
    "contracts": (
        "subprocess",
        "socket",
        "http",
        "urllib",
    ),
}


def _layer_of(module: str) -> str | None:
    """Return the questor sub-layer owning ``module`` (e.g. 'questor.kernel.x')."""
    parts = module.split(".")
    if len(parts) >= 2 and parts[0] == _ROOT_PKG:
        return parts[1] if parts[1] in LAYER_RANK else None
    return None


def _referenced_modules(node: ast.AST) -> list[tuple[int, str]]:
    """Yield (lineno, module_name) for every import this node makes, incl. dynamic ones."""
    found: list[tuple[int, str]] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Import):
            for alias in child.names:
                found.append((child.lineno, alias.name))
        elif isinstance(child, ast.ImportFrom) and child.module and not child.level:
            found.append((child.lineno, child.module))
        elif isinstance(child, ast.Call):
            func = child.func
            dyn = (isinstance(func, ast.Attribute) and func.attr == "import_module") or (
                isinstance(func, ast.Name) and func.id == "__import__"
            )
            if dyn and child.args and isinstance(child.args[0], ast.Constant) and isinstance(child.args[0].value, str):
                found.append((child.lineno, child.args[0].value))
    return found


def _referenced_layers(node: ast.AST) -> list[tuple[int, str]]:
    """Yield (lineno, imported questor sub-layer) for a node, incl. dynamic ones."""
    return [(lineno, layer) for lineno, module in _referenced_modules(node) if (layer := _layer_of(module))]


def analyze_source(source: str, own_layer: str, path: str = "<string>") -> list[str]:
    """Return violation messages for outer-layer imports and forbidden-module imports."""
    tree = ast.parse(source)
    violations: list[str] = []
    own_rank = LAYER_RANK.get(own_layer, -1)
    for lineno, imported in _referenced_layers(tree):
        if imported in CROSS_CUTTING:
            continue
        if LAYER_RANK.get(imported, -1) > own_rank:
            violations.append(
                f"{path}:{lineno}: layer '{own_layer}' must not import outer "
                f"layer '{imported}' (C1/C14)"
            )
    forbidden = FORBIDDEN_IMPORTS.get(own_layer, ())
    for lineno, module in _referenced_modules(tree):
        if any(module == bad or module.startswith(bad + ".") for bad in forbidden):
            violations.append(
                f"{path}:{lineno}: layer '{own_layer}' must not import '{module}' (T20 forbidden)"
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
    """Prove the guard flags a bad dynamic import, a forbidden import, and passes a good one."""
    bad = 'import importlib\nimportlib.import_module("questor.surfaces")\n'
    forbidden = 'import subprocess\n'
    surfaces_reduce = 'from questor.state.reduce import reduce\n'
    good = "from questor.contracts import events\n"
    bad_hits = analyze_source(bad, "kernel")
    forbidden_hits = analyze_source(forbidden, "capabilities")
    surfaces_hits = analyze_source(surfaces_reduce, "surfaces")
    good_hits = analyze_source(good, "kernel")
    ok = bool(bad_hits) and bool(forbidden_hits) and bool(surfaces_hits) and not good_hits
    print(f"self-test: dyn-import flagged={bool(bad_hits)} forbidden-caps flagged={bool(forbidden_hits)} surfaces-reduce flagged={bool(surfaces_hits)} clean-passed={not good_hits}")
    for msg in (*bad_hits, *forbidden_hits, *surfaces_hits):
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
