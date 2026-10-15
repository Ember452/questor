#!/usr/bin/env python3
"""One-click local P0 DoD check (in-process; CI adds ruff/lint-imports/pytest).

Verifies the skeleton cold-imports across every layer, constructor invariants
hold, the layering + wire-contract guards pass, and the AST guard can go red.
Exit code 0 == P0 interface-skeleton DoD met (design docs are separate).
"""

from __future__ import annotations

import importlib
import importlib.util
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LAYERS = [
    "contracts",
    "state",
    "kernel",
    "capabilities",
    "policy",
    "providers",
    "surfaces",
    "config",
    "observability",
]
MODULES = [
    "questor",
    *(f"questor.{layer}" for layer in LAYERS),
    "questor.contracts.events",
    "questor.contracts.ports",
    "questor.contracts.policy",
    "questor.contracts.tool",
    "questor.state.domain_state",
    "questor.kernel.loop",
    "questor.kernel.events",
    "questor.kernel.permissions",
    "questor.capabilities.tools.read",
    "questor.providers.litellm_adapter",
    "questor.providers.store_sqlite",
    "questor.surfaces.cli",
    "questor.policy.null_policy",
]


def _load_guard(filename: str, name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _check(desc: str, ok: bool) -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {desc}")
    return ok


def main() -> int:
    results: list[bool] = []

    print("1. cold import every layer + key modules")
    try:
        for mod in MODULES:
            importlib.import_module(mod)
        results.append(_check(f"imported {len(MODULES)} modules", True))
    except Exception as exc:  # noqa: BLE001
        results.append(_check(f"import failed: {exc}", False))

    print("2. constructor invariants (design/01 terminal consistency)")
    from questor.contracts.state_schema import RunStatus
    from questor.state.domain_state import Run

    try:
        Run(run_id="run_x1", status=RunStatus.COMPLETED)  # missing completed_at
        results.append(_check("terminal Run without completed_at rejected", False))
    except ValueError:
        results.append(_check("terminal Run without completed_at rejected", True))

    print("3. AST layering guard self-test (must be able to go red)")
    ast_guard = _load_guard("check_layering_ast.py", "check_layering_ast")
    results.append(_check("AST guard self_test == 0", ast_guard.self_test() == 0))

    print("4. wire-contract single source (schema <-> EventType)")
    proto = _load_guard("check_protocol_schema.py", "check_protocol_schema")
    results.append(_check("protocol drift check == 0", proto.check() == 0))

    print("5. no naive timestamps accepted")
    from questor.contracts.state_schema import Message, Role

    try:
        Message(id="msg_x", role=Role.USER, content=(), seq=0, created_at=datetime(2020, 1, 1))
        results.append(_check("naive Message timestamp rejected", False))
    except ValueError:
        results.append(_check("naive Message timestamp rejected", True))

    ok = all(results)
    print("\nP0 DoD (in-process):", "ALL PASS" if ok else "FAILURES PRESENT")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
