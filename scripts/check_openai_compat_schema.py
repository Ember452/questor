#!/usr/bin/env python3
"""OpenAI-compat wire drift gate (HARD C6/C15; ADR-0043).

Asserts:
1. ``protocol/openai_compat.schema.json`` is a well-formed JSON Schema (chunk + error $defs present);
2. the projection adapter's consumed questor types (``openai_compat.PROJECTED_EVENT_TYPES``) are all
   real ``contracts`` EventType members (mapping never references a phantom event);
3. the Python wire builders (``make_chunk``/``error_object``) emit shapes that VALIDATE against the
   declared wire schema — i.e. code and schema cannot silently drift apart;
4. (self-test) the schema rejects tampering (extra top-level field via ``additionalProperties:false``,
   wrong ``object`` const, out-of-enum ``finish_reason``) and detects mapping drift — fail-on-empty
   on every layer so a silent scope-shrink is a hard error, never a pass.

Usage:
    uv run python scripts/check_openai_compat_schema.py --check
    uv run python scripts/check_openai_compat_schema.py --self-test
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from questor.contracts.events import EventType
from questor.contracts.openai_wire import error_object, make_chunk
from questor.surfaces.openai_compat import PROJECTED_EVENT_TYPES

SCHEMA_PATH = Path("protocol/openai_compat.schema.json")


def _contract_types() -> set[str]:
    return {v for k, v in vars(EventType).items() if not k.startswith("_") and isinstance(v, str)}


def _load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _validator(schema: dict[str, Any], name: str) -> Draft202012Validator:
    return Draft202012Validator(schema["$defs"][name])


def _chunk_fixtures() -> list[dict[str, Any]]:
    return [
        make_chunk("chatcmpl-1", 1700000000, "questor", {"role": "assistant", "content": ""}, x_questor={"run_id": "r1"}),
        make_chunk("chatcmpl-1", 1700000000, "questor", {"content": "hi"}),
        make_chunk("chatcmpl-1", 1700000000, "questor", {}, finish_reason="stop"),
    ]


def _bad_chunk_fixtures() -> list[dict[str, Any]]:
    good = _chunk_fixtures()[0]
    over_field = {**json.loads(json.dumps(good)), "leak": "x"}  # 顶层多余字段 → additionalProperties:false 判红
    wrong_object = {**json.loads(json.dumps(good)), "object": "chat.completion.wrong"}
    bad_finish = json.loads(json.dumps(good))
    bad_finish["choices"][0]["finish_reason"] = "totally_bogus"
    return [over_field, wrong_object, bad_finish]


def _mapping_drift(schema_types_ok: bool) -> bool:
    """True = 映射集含未知 questor 事件（漂移）。"""
    return not PROJECTED_EVENT_TYPES <= _contract_types() or not schema_types_ok


def check() -> int:
    schema = _load_schema()
    Draft202012Validator.check_schema(schema)  # raises if malformed
    if {"chat_completion_chunk", "error_object"} - set(schema["$defs"]):
        print("openai_compat schema missing required $defs (chat_completion_chunk/error_object)", file=sys.stderr)
        return 1
    if not PROJECTED_EVENT_TYPES:
        print("fail-on-empty: PROJECTED_EVENT_TYPES is empty (adapter mapping vanished)", file=sys.stderr)
        return 2
    phantom = PROJECTED_EVENT_TYPES - _contract_types()
    if phantom:
        print(f"mapping references unknown questor event types: {sorted(phantom)}", file=sys.stderr)
        return 1
    chunk_v = _validator(schema, "chat_completion_chunk")
    err_v = _validator(schema, "error_object")
    for chunk in _chunk_fixtures():
        if not chunk_v.is_valid(chunk):
            print(f"builder make_chunk output fails wire schema: {chunk}", file=sys.stderr)
            return 1
    if not err_v.is_valid(error_object("unsupported_modality", "provider capability not supported")):
        print("builder error_object output fails wire schema", file=sys.stderr)
        return 1
    print(f"openai_compat wire OK: schema well-formed; {len(PROJECTED_EVENT_TYPES)} projected event types all real; builders match schema")
    return 0


def self_test() -> int:
    schema = _load_schema()
    Draft202012Validator.check_schema(schema)
    chunk_v = _validator(schema, "chat_completion_chunk")
    err_v = _validator(schema, "error_object")

    valid_ok = all(chunk_v.is_valid(c) for c in _chunk_fixtures()) and err_v.is_valid(error_object("c", "m"))
    bad_rejected = all(not chunk_v.is_valid(b) for b in _bad_chunk_fixtures())
    detects_drift = bool((PROJECTED_EVENT_TYPES | {"bogus_event"}) - _contract_types())  # 引入幻影类型必被发现
    mapping_clean = not _mapping_drift(True)
    ok = valid_ok and bad_rejected and detects_drift and mapping_clean and bool(PROJECTED_EVENT_TYPES)
    print(
        "self-test: "
        f"builders-valid={valid_ok} tamper-rejected={bad_rejected} "
        f"detects-drift={bool(detects_drift)} mapping-clean={mapping_clean} non-empty={bool(PROJECTED_EVENT_TYPES)}"
    )
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
