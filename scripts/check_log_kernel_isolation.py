#!/usr/bin/env python3
"""Log-kernel isolation guard (ADR-0027; G-L1/G-L2; DESIGN §3/§15).

The logging **kernel** — the nine files under ``src/questor/observability`` except
``projection.py`` (the one sanctioned adapter) — must stay free of every *other*
questor layer, not even ``contracts``, so that "extract the package" remains a
purely mechanical directory move. This is the mechanical backstop for import-linter
contract 5 (an intent declaration), and unlike import-linter it also catches
dynamic imports and fails on an empty/renamed scan (C15).

- **G-L1**: no ``questor.*`` reference (static *or* dynamic) outside
  ``questor.observability.*`` in any kernel file (siblings move together).
- **G-L2**: no name bound from an external questor module may appear in a function
  signature / ``AnnAssign`` annotation (the ``fields`` value domain must never widen
  to a questor type).

Reuses the single import walker from ``check_layering_ast`` (plan §T2.15: 不建重复 walker).

Usage:
    uv run python scripts/check_log_kernel_isolation.py            # scan real tree
    uv run python scripts/check_log_kernel_isolation.py --self-test # prove it can go red
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

#: Nine kernel files. ``projection.py`` is deliberately absent — it is the adapter
#: layer and is the ONLY observability file allowed to import ``questor.contracts``.
KERNEL_FILES: tuple[str, ...] = (
    "observability/entry.py",
    "observability/scope.py",
    "observability/redact.py",
    "observability/exporter.py",
    "observability/sink_console.py",
    "observability/sink_file.py",
    "observability/bridge.py",
    "observability/pipeline.py",
    "observability/configure.py",
)

#: Files under ``observability/`` that are sanctioned to be OUTSIDE the kernel list: the package
#: init (docstring only) and the one adapter layer. Anything else that shows up there must be
#: added to KERNEL_FILES explicitly -- otherwise a 10th kernel file with a forbidden import would
#: simply never be scanned (guard scope silently *widens*, the mirror image of fail-on-empty).
SANCTIONED_NON_KERNEL: frozenset[str] = frozenset(
    {
        "observability/__init__.py",
        "observability/projection.py",
    }
)


def _external_questor(module: str) -> bool:
    """True for a questor reference that is *not* the kernel's own package sibling."""
    return module.startswith("questor.") and not module.startswith("questor.observability")


def _annotation_nodes(tree: ast.AST) -> list[ast.expr]:
    out: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
                if arg.annotation is not None:
                    out.append(arg.annotation)
            if node.returns is not None:
                out.append(node.returns)
        elif isinstance(node, ast.AnnAssign) and node.annotation is not None:
            out.append(node.annotation)
    return out


def _names_in(node: ast.expr) -> set[str]:
    found: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            found.add(child.id)
        elif isinstance(child, ast.Attribute):
            found.add(child.attr)
    return found


def scan_source(source: str, path: str) -> list[str]:
    """Return G-L1/G-L2 violations for one kernel file's source."""
    from check_layering_ast import _referenced_modules

    tree = ast.parse(source)
    violations: list[str] = []
    # G-L1: any static or dynamic reference to a non-observability questor layer.
    for lineno, module in _referenced_modules(tree):
        if _external_questor(module):
            violations.append(f"{path}:{lineno}: logging kernel must not reference '{module}' (G-L1: kernel is layer-free)")
    # G-L2: a name bound from an external questor module must not surface in an annotation.
    external_names = {
        alias.asname or alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module and _external_questor(node.module)
        for alias in node.names
    }
    for ann in _annotation_nodes(tree):
        for name in sorted(_names_in(ann)):
            if name in external_names:
                violations.append(f"{path}:{getattr(ann, 'lineno', '?')}: annotation uses external questor type '{name}' (G-L2: fields/signature must be whitelist scalars)")
    return violations


def _scope_violations(found: list[str], root: Path) -> list[str]:
    """Anti-widening: every ``observability/*.py`` file (root-relative path) must be kernel or a named adapter."""
    covered = set(KERNEL_FILES) | set(SANCTIONED_NON_KERNEL)
    return [
        f"{root / rel}: neither in KERNEL_FILES nor a sanctioned adapter "
        "(add it explicitly or the isolation scan silently skips it)"
        for rel in sorted(found)
        if rel not in covered
    ]


def check(root: Path) -> tuple[list[str], int]:
    """Scan every kernel file under ``root``; flag missing files (fail-on-empty) and new files."""
    violations: list[str] = []
    scanned = 0
    for rel in KERNEL_FILES:
        file = root / rel
        if not file.exists():
            violations.append(f"fail-on-empty: kernel file '{rel}' not found under {root} (guard scope silently shrank)")
            continue
        scanned += 1
        violations += scan_source(file.read_text(encoding="utf-8"), str(file))
    pkg = root / "observability"
    if pkg.is_dir():
        # 路径必须与 KERNEL_FILES 同基准（相对 root），否则清单比对全体对不上、把内核文件自己报成越界。
        found = [p.relative_to(root).as_posix() for p in sorted(pkg.glob("*.py"))]
        violations += _scope_violations(found, root)
    return violations, scanned


def self_test() -> int:
    """Prove the guard flags an external static import, a dynamic import, and a leaking
    annotation, while passing a sibling import and a pure-stdlib kernel file."""
    external_import = "import questor.contracts\n"
    dynamic_import = 'import importlib\nimportlib.import_module("questor.contracts")\n'
    leaking_annotation = "from questor.contracts.events import Envelope\n\n\ndef f(x: Envelope) -> Envelope:\n    return x\n"
    sibling_ok = "from questor.observability.entry import LogEntry\n\n\ndef f(x: LogEntry) -> None:\n    pass\n"
    stdlib_ok = "import json\nfrom dataclasses import dataclass\n\n\n@dataclass\nclass LogEntry:\n    ts: int\n"

    red_import = scan_source(external_import, "entry.py")
    red_dynamic = scan_source(dynamic_import, "entry.py")
    red_annotation = scan_source(leaking_annotation, "entry.py")
    ok_sibling = scan_source(sibling_ok, "entry.py")
    ok_stdlib = scan_source(stdlib_ok, "scope.py")
    # G-L2 must fire on the annotation independently of the import line.
    annotation_only = any("G-L2" in m for m in red_annotation)

    ok = bool(red_import) and bool(red_dynamic) and annotation_only and not ok_sibling and not ok_stdlib
    # Anti-widen: a new observability file outside the kernel list and outside the sanctioned
    # adapters must go red (anti-shrink is the fail-on-empty branch in check()).
    widen = _scope_violations(["observability/entry.py", "observability/sneaky.py"], Path("src/questor"))
    scope_clean = _scope_violations([*KERNEL_FILES, "observability/__init__.py", "observability/projection.py"], Path("src/questor"))
    ok = ok and bool(widen) and not scope_clean
    print(
        f"self-test: external-import={bool(red_import)} dynamic-import={bool(red_dynamic)} "
        f"annotation-leak={annotation_only} sibling-passed={not ok_sibling} stdlib-passed={not ok_stdlib} "
        f"scope-widening-caught={bool(widen)}"
    )
    for msg in (*red_import, *red_dynamic, *red_annotation, *widen):
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
    for msg in violations:
        print(msg, file=sys.stderr)
    if scanned == 0 and violations:
        print("log-kernel isolation: FAIL (no kernel files found)", file=sys.stderr)
        return 2
    if violations:
        return 1
    print(f"log-kernel isolation: {scanned} kernel files scanned, all layer-free (G-L1/G-L2)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
