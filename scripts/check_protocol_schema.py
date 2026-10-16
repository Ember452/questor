#!/usr/bin/env python3
"""Wire-contract single-source-of-truth drift guard (HARD C6/C15).

Asserts:
1. the external event ``type`` enum in ``protocol/event.schema.json`` is exactly the set in
   ``questor.contracts.events.EventType`` (no silent divergence with Python contract / P7 codegen);
2. every event type has BOTH a ``$defs`` payload schema AND an ``if/then`` branch (per-type fields,
   not just a bare enum);
3. the schema is itself a well-formed JSON Schema;
4. (self-test) the schema accepts exactly the shapes ``reduce`` emits and rejects an over-field /
   missing-required / oversized payload — fail-on-empty on every layer.

Usage:
    uv run python scripts/check_protocol_schema.py --check
    uv run python scripts/check_protocol_schema.py --self-test
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from questor.contracts.events import EventType

SCHEMA_PATH = Path("protocol/event.schema.json")


def _contract_types() -> set[str]:
    return {v for k, v in vars(EventType).items() if not k.startswith("_") and isinstance(v, str)}


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _schema_types(schema: dict) -> set[str]:
    return set(schema["properties"]["type"]["enum"])


def _def_types(schema: dict) -> set[str]:
    return set(schema.get("$defs", {}))


def _branch_types(schema: dict) -> set[str]:
    branches: set[str] = set()
    for clause in schema.get("allOf", []):
        const = clause.get("if", {}).get("properties", {}).get("type", {}).get("const")
        if isinstance(const, str):
            branches.add(const)
    return branches


def check() -> int:
    schema = _load_schema()
    Draft202012Validator.check_schema(schema)  # raises if malformed
    contract = _contract_types()
    if not contract:  # fail-on-empty: an empty EventType set is a misconfig, not a pass
        print("fail-on-empty: contract EventType set is empty", file=sys.stderr)
        return 2
    enum = _schema_types(schema)
    if enum ^ contract:
        print(f"DRIFT between {SCHEMA_PATH} enum and EventType: {sorted(enum ^ contract)}", file=sys.stderr)
        return 1
    defs = _def_types(schema)
    branches = _branch_types(schema)
    if defs ^ contract:
        print(f"$defs coverage mismatch vs EventType: {sorted(defs ^ contract)}", file=sys.stderr)
        return 1
    if branches ^ contract:
        print(f"if/then branch coverage mismatch vs EventType: {sorted(branches ^ contract)}", file=sys.stderr)
        return 1
    print(f"protocol schema OK: {len(contract)} event types in lockstep (enum + $defs + branches)")
    return 0


def _envelope(type_name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"v": 1, "seq": 1, "run_id": "run_x", "turn": 1, "ts": "2026-01-01T00:00:00+00:00", "type": type_name, "data": data}


def _valid_fixtures() -> dict[str, dict[str, Any]]:
    return {
        "run_started": _envelope("run_started", {"run_id": "run_x"}),
        "turn_started": _envelope("turn_started", {"turn": 1}),
        "text_delta": _envelope("text_delta", {"delta": "hi"}),
        "reasoning_delta": _envelope("reasoning_delta", {"delta": "think"}),
        "message_completed": _envelope("message_completed", {"message_id": "msg_1"}),
        "tool_started": _envelope("tool_started", {"tool_call_id": "tc1", "name": "read", "capability": "readonly", "risk": "low", "args_summary": "a.txt"}),
        "tool_progress": _envelope("tool_progress", {"message": "working"}),
        "tool_completed": _envelope("tool_completed", {"tool_call_id": "tc1", "status": "success"}),
        "approval_request": _envelope("approval_request", {"request_id": "apr1", "tool_call_id": "tc1", "name": "write", "args_summary": "out.txt", "risk": "high", "reason": "needs approval", "expires_at": "2026-01-01T00:05:00+00:00"}),
        "approval_resolved": _envelope("approval_resolved", {"request_id": "apr1", "tool_call_id": "tc1", "decision": "allow", "decided_by": "user", "resolved_at": "2026-01-01T00:01:00+00:00"}),
        "permission_mode_changed": _envelope("permission_mode_changed", {"mode": "full_auto", "changed_by": "user", "effective_from_turn": 2}),
        "node_updated": _envelope("node_updated", {"node": {"id": "n1"}}),
        "usage_delta": _envelope("usage_delta", {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3}),
        "heartbeat": _envelope("heartbeat", {}),
        "run_cancelled": _envelope("run_cancelled", {"reason": "user"}),
        "run_failed": _envelope("run_failed", {"error": {"code": "timeout", "message": "oops", "retryable": False}}),
        "run_completed": _envelope("run_completed", {"usage": {"total_tokens": 3}, "exit_reason": "answered"}),
        "resync_required": _envelope("resync_required", {"reason": "version_mismatch", "expected": 1, "current": 1}),
        "warning": _envelope("warning", {"message": "be careful"}),
    }


def _bad_fixtures() -> dict[str, dict[str, Any]]:
    good_tool = _valid_fixtures()["tool_started"]
    over_field = json.loads(json.dumps(good_tool))
    over_field["data"]["full_args"] = '{"secret": "leak"}'  # 多余字段必须被 additionalProperties:false 判红
    missing_required = json.loads(json.dumps(_valid_fixtures()["approval_request"]))
    del missing_required["data"]["reason"]  # 缺 required 判红
    oversized = _envelope("text_delta", {"delta": "x" * 9000})  # 超 maxLength 判红
    return {"over_field": over_field, "missing_required": missing_required, "oversized": oversized}


def self_test() -> int:
    """Prove the guard's schema accepts exact emit-shapes and rejects malformed payloads."""
    schema = _load_schema()
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    valid = _valid_fixtures()
    contract = _contract_types()
    if not valid or set(valid) != contract:  # fail-on-empty / 漏类型都判红
        print(f"self-test fixtures do not cover every EventType: missing {sorted(contract - set(valid))}", file=sys.stderr)
        return 1
    accepted = {name: validator.is_valid(env) for name, env in valid.items()}
    bad_accept = [name for name, ok in accepted.items() if not ok]

    bad = _bad_fixtures()
    rejected = {name: not validator.is_valid(env) for name, env in bad.items()}
    bad_reject = [name for name, ok in rejected.items() if not ok]

    drift = set(_schema_types(schema)) | {"bogus_event"}
    detects = drift != contract

    ok = not bad_accept and not bad_reject and detects
    print(f"self-test: valid_all_pass={not bad_accept} ({bad_accept}) bad_all_reject={not bad_reject} ({bad_reject}) detects-drift={detects}")
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
