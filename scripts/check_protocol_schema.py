#!/usr/bin/env python3
"""Wire-contract single-source-of-truth drift guard (HARD C6/C15).

Asserts that the external event ``type`` enum in ``protocol/event.schema.json``
is exactly the set in ``questor.contracts.events.EventType`` — so the JSON
Schema, the Python contract, and (later, P7) codegen'd TS can never silently
diverge. Also validates the schema is itself a well-formed JSON Schema.

Usage:
    uv run python scripts/check_protocol_schema.py --check
    uv run python scripts/check_protocol_schema.py --self-test
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

from questor.contracts.events import EventType

SCHEMA_PATH = Path("protocol/event.schema.json")


def _contract_types() -> set[str]:
    return {v for k, v in vars(EventType).items() if not k.startswith("_") and isinstance(v, str)}


def _schema_types(schema: dict) -> set[str]:
    return set(schema["properties"]["type"]["enum"])


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def check() -> int:
    schema = _load_schema()
    Draft202012Validator.check_schema(schema)  # raises if malformed
    drift = _schema_types(schema) ^ _contract_types()
    if drift:
        print(f"DRIFT between {SCHEMA_PATH} and EventType: {sorted(drift)}", file=sys.stderr)
        return 1
    print(f"protocol schema OK: {len(_contract_types())} event types in lockstep")
    return 0


def self_test() -> int:
    """Prove the guard detects drift (synthetic) and passes on the real files."""
    schema = _load_schema()
    good = _schema_types(schema) == _contract_types()
    tampered = set(_schema_types(schema)) | {"bogus_event"}
    tampered_schema = {"properties": {"type": {"enum": sorted(tampered)}}}
    detects = _schema_types(tampered_schema) != _contract_types()
    ok = good and detects
    print(f"self-test: real-in-sync={good} detects-drift={detects}")
    print("self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    return self_test() if args.self_test else check()


if __name__ == "__main__":
    raise SystemExit(main())
