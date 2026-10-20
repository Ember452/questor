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

from questor.contracts.artifacts import OutputBudget
from questor.contracts.errors import MAX_ERROR_MESSAGE_CHARS
from questor.contracts.events import EventType
from questor.contracts.sidecar_status import _MAX_DETAIL_LEN, SIDECAR_LIFECYCLE_STATES, SIDECAR_STATUS_FIELDS
from questor.kernel.events import EXTERNAL_EVENT_FIELDS
from questor.state.reduce import _MSG_FINAL_TEXT_CHARS

SCHEMA_PATH = Path("protocol/event.schema.json")
SIDEcar_STATUS_SCHEMA_PATH = Path("protocol/sidecar_status.schema.json")


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


def _def_prop_names(def_body: object) -> set[str]:
    """一个 type 的 $defs 体内声明的属性名集（非对象/无 properties → 空集）。"""
    if isinstance(def_body, dict):
        props = def_body.get("properties")
        if isinstance(props, dict):
            return set(props)
    return set()


def _field_drift(schema: dict) -> list[str]:
    """字段级漂移（C15 / design/02 §6）：每个 type 的 `$defs` 属性名集必须 == contracts 的 `EXTERNAL_EVENT_FIELDS` 白名单键集。

    这是把三处 lockstep 从“type 集”下推到“字段集”的门：改名/增删字段只改 schema 不改 contracts（或反之）就判红。
    白名单为 `None`（尚未定形的透传 draft，当前无）跳过，不强行要求。
    """
    defs = schema.get("$defs", {})
    drift: list[str] = []
    for t in sorted(_contract_types()):
        allowed = EXTERNAL_EVENT_FIELDS.get(t)
        if allowed is None:
            continue
        props = _def_prop_names(defs.get(t))
        if props != set(allowed):
            drift.append(
                f"field drift on '{t}': schema $defs props {sorted(props)} != contracts whitelist {sorted(set(allowed))}"
            )
    return drift


def _sidecar_status_drift(status: dict) -> list[str]:
    """§6-5：进程级 status 面的字段级 lockstep（传入的 status schema ⟂ contracts）。

    state 枚举 == ``SIDECAR_LIFECYCLE_STATES``；顶层属性集 == ``SIDECAR_STATUS_FIELDS``。任一侧增删/改名只改一处即判红。
    传**内存中的 dict**（便于 self-test 喂篡改副本），不做磁盘 IO。
    """
    props = status.get("properties", {})
    enum = set(props.get("state", {}).get("enum", []))
    drift: list[str] = []
    if enum != set(SIDECAR_LIFECYCLE_STATES):
        drift.append(f"sidecar_status state enum {sorted(enum)} != contracts {sorted(SIDECAR_LIFECYCLE_STATES)}")
    names = set(props)
    if names != set(SIDECAR_STATUS_FIELDS):
        drift.append(f"sidecar_status field set {sorted(names)} != contracts whitelist {sorted(SIDECAR_STATUS_FIELDS)}")
    return drift


def _max_length_drift(event_schema: dict, status_schema: dict) -> list[str]:
    """maxLength **数值**单一真源交叉核对（#165）：schema 里声明的上限必须 == Python 常量。

    旧守卫只比字段名，不比数值：改 schema maxLength 或 Python 常量之一不会报红，
    而“bounded”只是口头。本函数把三处有界字段（final_text / error.message / sidecar detail）钉成机守。"""

    def _maxlen(node: object, *keys: str) -> object:
        cur: object = node
        for k in keys:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(k)
        return cur

    checks = [
        (
            _maxlen(event_schema, "$defs", "message_completed", "properties", "final_text", "maxLength"),
            _MSG_FINAL_TEXT_CHARS,
            "message_completed.final_text vs reduce._MSG_FINAL_TEXT_CHARS",
        ),
        (
            _maxlen(event_schema, "$defs", "user_message", "properties", "text", "maxLength"),
            OutputBudget().model_result_bytes,
            "user_message.text vs artifacts.OutputBudget.model_result_bytes",
        ),
        (
            _maxlen(event_schema, "$defs", "run_failed", "properties", "error", "properties", "message", "maxLength"),
            MAX_ERROR_MESSAGE_CHARS,
            "run_failed.error.message vs errors.MAX_ERROR_MESSAGE_CHARS",
        ),
        (
            _maxlen(status_schema, "properties", "detail", "maxLength"),
            _MAX_DETAIL_LEN,
            "sidecar_status.detail vs _MAX_DETAIL_LEN",
        ),
    ]
    drift: list[str] = []
    for schema_val, py_val, label in checks:
        if schema_val != py_val:
            drift.append(f"maxLength drift on '{label}': schema {schema_val!r} != python {py_val!r}")
    return drift


def check() -> int:
    schema = _load_schema()
    Draft202012Validator.check_schema(schema)  # raises if malformed
    status_schema = json.loads(SIDEcar_STATUS_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(status_schema)  # §6-5：status 面自身亦须良构
    status_drift = _sidecar_status_drift(status_schema)
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
    drift = _field_drift(schema)  # 字段级：$defs 属性集 == contracts 白名单键集
    if drift:
        for line in drift:
            print(line, file=sys.stderr)
        return 1
    if status_drift:  # §6-5：进程级 status 面的 state 枚举/字段集与 contracts lockstep
        for line in status_drift:
            print(line, file=sys.stderr)
        return 1
    ml_drift = _max_length_drift(schema, status_schema)  # #165：bounded 上限数值也必须 lockstep
    if ml_drift:
        for line in ml_drift:
            print(line, file=sys.stderr)
        return 1
    print(
        f"protocol schema OK: {len(contract)} event types in lockstep (enum + $defs + branches + per-type field sets) + sidecar_status"
    )
    return 0


def _envelope(type_name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"v": 1, "seq": 1, "run_id": "run_x", "turn": 1, "ts": "2026-01-01T00:00:00+00:00", "type": type_name, "data": data}


def _valid_fixtures() -> dict[str, dict[str, Any]]:
    return {
        "run_started": _envelope("run_started", {"run_id": "run_x", "policy_ref": {"id": "react", "fingerprint": "fp"}}),
        "turn_started": _envelope("turn_started", {"turn": 1}),
        "text_delta": _envelope("text_delta", {"delta": "hi"}),
        "reasoning_delta": _envelope("reasoning_delta", {"delta": "think"}),
        "message_completed": _envelope("message_completed", {"message_id": "msg_1"}),
        # B1 additive：user_message（用户原话进事实流；text 有界 + truncated）。
        "user_message": _envelope("user_message", {"text": "hello", "truncated": False}),
        # B6 additive：turn_completed（Stop 点；只带 usage/interrupted）。
        "turn_completed": _envelope("turn_completed", {"usage": {"total_tokens": 3}, "interrupted": False}),
        "tool_started": _envelope(
            "tool_started",
            {"tool_call_id": "tc1", "name": "read", "capability": "readonly", "risk": "low", "args_summary": "a.txt"},
        ),
        "tool_progress": _envelope("tool_progress", {"message": "working"}),
        "tool_completed": _envelope("tool_completed", {"tool_call_id": "tc1", "status": "success"}),
        "approval_request": _envelope(
            "approval_request",
            {
                "request_id": "apr1",
                "tool_call_id": "tc1",
                "name": "write",
                "args_summary": "out.txt",
                "risk": "high",
                "reason": "needs approval",
                "expires_at": "2026-01-01T00:05:00+00:00",
            },
        ),
        "approval_resolved": _envelope(
            "approval_resolved",
            {
                "request_id": "apr1",
                "tool_call_id": "tc1",
                "decision": "allow",
                "decided_by": "user",
                "resolved_at": "2026-01-01T00:01:00+00:00",
            },
        ),
        "permission_mode_changed": _envelope(
            "permission_mode_changed", {"mode": "full_auto", "changed_by": "user", "effective_from_turn": 2}
        ),
        "node_updated": _envelope("node_updated", {"node_id": "n1", "status": "pending"}),
        "usage_delta": _envelope("usage_delta", {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3}),
        "heartbeat": _envelope("heartbeat", {}),
        "run_cancelled": _envelope("run_cancelled", {"reason": "user"}),
        "run_failed": _envelope("run_failed", {"error": {"code": "timeout", "message": "oops", "retryable": False}}),
        "run_completed": _envelope("run_completed", {"usage": {"total_tokens": 3}, "exit_reason": "answered"}),
        "resync_required": _envelope("resync_required", {"reason": "version_mismatch", "expected": 1, "current": 1}),
        "warning": _envelope("warning", {"message": "be careful"}),
        "memory_written": _envelope("memory_written", {"kind": "daily", "chunk_count": 2}),
        "peer_started": _envelope("peer_started", {"parent_run_id": "rp", "child_run_id": "rc", "node_id": "n1"}),
        "peer_ended": _envelope(
            "peer_ended",
            {"parent_run_id": "rp", "child_run_id": "rc", "node_id": "n1", "terminal_status": "completed", "resumable_hint": False},
        ),
        # P9 additive：tools_changed（live-only 告警，单 domain 枚举）+ run_started 带 additive policy_ref。
        "tools_changed": _envelope("tools_changed", {"domain": "tools"}),
        # P10 additive（ADR-0048）：compact_started 单 reason；compact_applied 只栅栏/有界量、无正文。
        "compact_started": _envelope("compact_started", {"reason": "kernel_token_pressure"}),
        "compact_applied": _envelope("compact_applied", {"baseline_seq": 7, "covered_from": 1, "covered_to": 3, "summary_bytes": 42}),
        # B10/ADR-0057：预警与跳闸是 durable 的，只带阈值/用量/计数（零正文）；窗口身份可为 null。
        "compact_warning": _envelope(
            "compact_warning",
            {"reason": "pressure", "trigger": "auto", "used_tokens": 120000, "threshold": 100000, "window_number": 1, "failures": 0},
        ),
        # B7 additive：memory_injected（live-only 审计条目，只条目 id + 计量）与 cache_break（三段 hash + 原因）。
        "memory_injected": _envelope("memory_injected", {"kind": "index", "entry_ids": ["MEMORY.md:1-1"], "lines": 3, "bytes": 240, "truncated": False}),
        "cache_break": _envelope("cache_break", {"system_hash": "sha256:aaa", "tools_hash": None, "history_hash": None, "reason": "cold", "breakpoints": 1}),
        # B8 additive：memory_consumed（命中不算消费，只有真读/引用才发）与 message_completed.citations。
        "memory_consumed": _envelope("memory_consumed", {"kind": "raw", "entry_id": "memory/2026-10-01.md:3-7", "tool_name": "read"}),
        # B9 additive：memory_deleted（撤回回执：只条目 id + 短原因；变更史只有事件流一份，C-7）。
        "memory_deleted": _envelope("memory_deleted", {"entry_id": "memory/2026-10-01.md:3-7", "reason": "user revoked"}),
    }


def _bad_fixtures() -> dict[str, dict[str, Any]]:
    good_tool = _valid_fixtures()["tool_started"]
    over_field = json.loads(json.dumps(good_tool))
    over_field["data"]["full_args"] = '{"secret": "leak"}'  # 多余字段必须被 additionalProperties:false 判红
    missing_required = json.loads(json.dumps(_valid_fixtures()["approval_request"]))
    del missing_required["data"]["reason"]  # 缺 required 判红
    oversized = _envelope("text_delta", {"delta": "x" * 9000})  # 超 maxLength 判红
    # B1：user_message.text 超 maxLength（= OutputBudget().model_result_bytes 的字节预算）必须被拒——
    # 「用户正文有界」不是口头，而是本 schema 的机守。
    user_message_oversized = _envelope("user_message", {"text": "x" * (OutputBudget().model_result_bytes + 1)})
    # P8 peer_*：非枚举终态 + 未知载荷字段（additionalProperties:false）都必被拒。
    peer_bad_status = _envelope("peer_ended", {"parent_run_id": "rp", "child_run_id": "rc", "node_id": "n1", "terminal_status": "weird"})
    peer_over_field = _envelope("peer_started", {"parent_run_id": "rp", "child_run_id": "rc", "node_id": "n1", "prompt": "leak"})
    # P9：tools_changed domain 不在枚举、run_started.policy_ref 多余字段（additionalProperties:false）都必须被拒。
    tools_bad_domain = _envelope("tools_changed", {"domain": "bogus"})
    policy_over_field = _envelope("run_started", {"run_id": "run_x", "policy_ref": {"id": "r", "fingerprint": "f", "leak": 1}})
    # P10 compact_*（ADR-0048）：compact_applied 额外携 summary_text 正文必须被 additionalProperties:false 拒（C20）。
    compact_over_field = _envelope("compact_applied", {"baseline_seq": 7, "covered_from": 1, "covered_to": 3, "summary_bytes": 42, "summary_text": "leaked body"})
    # B10 compact_warning：reason 是闭集（pressure/breaker_tripped），不接受自由文本（不泄正文）。
    compact_warning_bad_reason = _envelope("compact_warning", {"reason": "nearly out of context", "trigger": "auto"})
    # B6：turn_completed 不得携正文/额外字段（additionalProperties:false）。
    turn_completed_over_field = _envelope("turn_completed", {"usage": {}, "interrupted": False, "text": "leak"})
    # B7：memory_injected 不得携索引正文；cache_break 的 reason 必在枚举内、断点数不超 4 个预算。
    memory_injected_over_field = _envelope("memory_injected", {"kind": "index", "text": "leaked index body"})
    memory_injected_bad_kind = _envelope("memory_injected", {"kind": "bogus"})
    cache_break_bad_reason = _envelope("cache_break", {"reason": "magic", "breakpoints": 1})
    cache_break_over_budget = _envelope("cache_break", {"reason": "budget", "breakpoints": 9})
    # B8：memory_consumed 缺 entry_id 必拒（条目级归因不允许降为文件级）；citations 多余字段必拒。
    memory_consumed_missing_entry = _envelope("memory_consumed", {"kind": "raw"})
    citations_over_field = _envelope(
        "message_completed",
        {"message_id": "m1", "citations": {"entries": [{"path": "MEMORY.md", "line_start": 1, "line_end": 2, "text": "leaked body"}]}},
    )
    citations_missing_line_range = _envelope(
        "message_completed", {"message_id": "m1", "citations": {"entries": [{"path": "MEMORY.md"}]}}
    )
    # B9：memory_deleted 不得携被删正文（软删位 + 事件就是全部历吏，C-7/C18）。
    memory_deleted_with_body = _envelope("memory_deleted", {"entry_id": "MEMORY.md:1-2", "text": "leaked revoked body"})
    return {
        "over_field": over_field,
        "missing_required": missing_required,
        "oversized": oversized,
        "user_message_oversized": user_message_oversized,
        "peer_bad_status": peer_bad_status,
        "peer_over_field": peer_over_field,
        "tools_bad_domain": tools_bad_domain,
        "policy_over_field": policy_over_field,
        "compact_over_field": compact_over_field,
        "compact_warning_bad_reason": compact_warning_bad_reason,
        "turn_completed_over_field": turn_completed_over_field,
        "memory_injected_over_field": memory_injected_over_field,
        "memory_injected_bad_kind": memory_injected_bad_kind,
        "cache_break_bad_reason": cache_break_bad_reason,
        "cache_break_over_budget": cache_break_over_budget,
        "memory_consumed_missing_entry": memory_consumed_missing_entry,
        "citations_over_field": citations_over_field,
        "citations_missing_line_range": citations_missing_line_range,
        "memory_deleted_with_body": memory_deleted_with_body,
    }


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

    # 字段级门能判红：把某 type 的 $defs 属性改名（不动 contracts）→ _field_drift 必报；不改则不报。
    field_ok_when_aligned = not _field_drift(schema)
    import copy

    tampered = copy.deepcopy(schema)
    mc = tampered["$defs"]["message_completed"]["properties"]
    mc["final_text_TAMPERED"] = mc.pop("final_text")  # 只改 schema 字段名
    field_drift_caught = bool(_field_drift(tampered))

    # §6-5：status 面字段级门能判红——把 state 枚举值改名（不动 contracts）→ _sidecar_status_drift 必报；不改则不报。
    status_schema = json.loads(SIDEcar_STATUS_SCHEMA_PATH.read_text(encoding="utf-8"))
    status_ok_when_aligned = not _sidecar_status_drift(status_schema)
    tampered_status = copy.deepcopy(status_schema)
    se = tampered_status["properties"]["state"]["enum"]
    se[se.index("crashed")] = "crashhed_TAMPERED"
    status_drift_caught = bool(_sidecar_status_drift(tampered_status))

    # #165：maxLength 数值门能判红——改 schema 的 final_text maxLength（不动 Python）→ 必报。
    maxlen_ok_when_aligned = not _max_length_drift(schema, status_schema)
    tampered_ml = copy.deepcopy(schema)
    tampered_ml["$defs"]["message_completed"]["properties"]["final_text"]["maxLength"] = 9999
    maxlen_drift_caught = bool(_max_length_drift(tampered_ml, status_schema))

    ok = (
        not bad_accept
        and not bad_reject
        and detects
        and field_ok_when_aligned
        and field_drift_caught
        and status_ok_when_aligned
        and status_drift_caught
        and maxlen_ok_when_aligned
        and maxlen_drift_caught
    )
    print(
        f"self-test: valid_all_pass={not bad_accept} ({bad_accept}) bad_all_reject={not bad_reject} ({bad_reject}) detects-drift={detects} field-lockstep-green={field_ok_when_aligned} field-drift-caught={field_drift_caught} status-lockstep-green={status_ok_when_aligned} status-drift-caught={status_drift_caught}"
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
