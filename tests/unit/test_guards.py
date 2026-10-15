"""P0 DoD — mechanical guards are trustworthy (can go red; scan is real).

Loads the ``scripts/`` guard modules and asserts their ``--self-test`` fixtures
prove they can detect a violation (not false-green), and that the current tree
passes (C15: fail-on-empty + self-test).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ast_layering_guard_self_test() -> None:
    ast_guard = _load("check_layering_ast", "check_layering_ast.py")
    assert ast_guard.self_test() == 0  # flags a bad dynamic import, passes a good one


def test_ast_scan_current_tree_clean_and_nonempty() -> None:
    ast_guard = _load("check_layering_ast", "check_layering_ast.py")
    violations, scanned = ast_guard.check(REPO_ROOT / "src" / "questor")
    assert scanned > 0, "fail-on-empty: guard scanned nothing"
    assert violations == []


def test_ast_flags_concrete_violation() -> None:
    ast_guard = _load("check_layering_ast", "check_layering_ast.py")
    bad = "import questor.surfaces.cli\n"  # contracts must not import L6
    assert ast_guard.analyze_source(bad, "contracts")


def test_protocol_schema_sync() -> None:
    proto = _load("check_protocol_schema", "check_protocol_schema.py")
    assert proto.self_test() == 0
    assert proto.check() == 0
