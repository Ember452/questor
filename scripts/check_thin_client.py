#!/usr/bin/env python3
"""Thin-client guard for the desktop/web shell (HARD-CONSTRAINTS C14/C16/C17; STRUCTURE S5/S6).

The desktop is a *thin client*: it may only consume the event protocol and submit Commands over
HTTP+SSE. If anyone ports harness logic into the shell -- the event bus, a store, the permission
engine, out-of-band projection, or a second write path -- that silently breaks the single-source /
single-writer invariants across a process boundary (the exact "图省事跨层直调" red line).

This guard scans ``desktop/web/src/**`` (excluding the codegen'd ``generated/`` tree) and fails on:
1. a harness/business identifier leaking into the shell (denylist below);
2. the generated event envelope type referenced WITHOUT importing it from ``generated/`` (C15:
   event types must come only from the codegen'd single source);
3. fail-on-empty: zero scanned files means the target tree is missing/misconfigured, not a pass.

Usage:
    uv run python scripts/check_thin_client.py             # scan desktop/web/src
    uv run python scripts/check_thin_client.py --self-test  # prove it can go red

NOTE: identifiers are chosen to be code-distinct (not prose) so explanatory Chinese comments that
mention "reduce"/"权限" in prose do NOT false-positive. The scan is a heuristic backstop; package/
process boundaries + the HTTP+SSE-only transport (ADR-0007) remain the primary defense.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

#: 若这些 harness 标识出现在桌面源码里 => 业务/内核逻辑被下沉进壳（违反 S6/C14/C16/C17）。
BUSINESS_TOKENS: tuple[str, ...] = (
    "InProcessEventBus",
    "EventBus",
    "SQLiteStore",
    "SQLiteMemoryStore",
    "PermissionEngine",
    "PermissionCtx",
    "capability_floor",
    "StorePort",
    "log_envelope",
    "reduce(",
    "subprocess",
    "questor.",
)

#: 对外事件信封类型只能 import 自 codegen 产物 ``generated/``（C15 单一真源）。
GENERATED_EVENT_SYMBOL = "QuestorExternalEventProjectionV1"

_SRC_SUFFIXES = {".ts", ".tsx"}


def analyze_source(source: str, path: str, generated_symbol: str = GENERATED_EVENT_SYMBOL) -> list[str]:
    """返回该文件的违规信息（业务 token 下沉 / 事件类型未从 generated 导入）。

    ``generated_symbol`` 可参数化（OPT-10 壳中立）：默认仍是 Tauri/web 现用的信封类型名，
    换壳时只改命令行参数，不改守卫逻辑。
    """
    violations: list[str] = []
    for token in BUSINESS_TOKENS:
        if token in source:
            lineno = source[: source.index(token)].count("\n") + 1
            violations.append(f"{path}:{lineno}: thin client must not embed harness logic token {token!r} (S6/C14/C16)")
    if generated_symbol in source:
        # 引用了对外事件信封类型，必须有一条 import ... from '.../generated/...' 提供来源。
        imported_from_generated = any(
            ("import" in line and generated_symbol in line and "generated" in line)
            for line in source.splitlines()
        )
        if not imported_from_generated:
            violations.append(
                f"{path}: event envelope type {generated_symbol!r} must be imported from the codegen'd generated/ tree (C15)"
            )
    return violations


def check(root: Path, generated_symbol: str = GENERATED_EVENT_SYMBOL) -> tuple[list[str], int]:
    """扫描 ``root`` 下所有 TS 源（排除 generated/）；返回 (违规, 扫描文件数)。"""
    violations: list[str] = []
    scanned = 0
    for ts in sorted(root.rglob("*")):
        if ts.suffix not in _SRC_SUFFIXES or not ts.is_file():
            continue
        if "generated" in ts.parts:  # codegen 产物本身不参与瘦客户端业务扫描
            continue
        scanned += 1
        violations += analyze_source(ts.read_text(encoding="utf-8"), str(ts), generated_symbol)
    return violations, scanned


def self_test() -> int:
    """证明守卫能判红：业务 token 下沉、事件类型未从 generated 导入；并证明干净样板放行。"""
    business_leak = "class X { constructor(bus){ this.bus = new InProcessEventBus(store) } }\n"
    reduce_call = "function apply(s, c){ return reduce(s, c) }\n"
    event_no_generated = 'import { QuestorExternalEventProjectionV1 } from "../types";\nexport type E = QuestorExternalEventProjectionV1;\n'
    clean = 'import type { QuestorExternalEventProjectionV1 as Event } from "../generated/event";\nexport const s: Event | null = null;\n'

    leak_hits = analyze_source(business_leak, "a.ts")
    reduce_hits = analyze_source(reduce_call, "b.ts")
    drift_hits = analyze_source(event_no_generated, "c.ts")
    clean_hits = analyze_source(clean, "d.ts")
    # OPT-10：参数化信封类型名——别的壳（Electron/IDE）用另一个名字时同样能拦。
    other_symbol = "ElectronEventProjectionV1"
    param_drift = analyze_source(
        f'import {{ {other_symbol} }} from "../types";\nexport type E = {other_symbol};\n', "e.ts", other_symbol
    )
    param_clean = analyze_source(
        f'import type {{ {other_symbol} }} from "../generated/event";\nexport const s: {other_symbol} | null = null;\n',
        "f.ts",
        other_symbol,
    )
    ok = (
        bool(leak_hits)
        and bool(reduce_hits)
        and bool(drift_hits)
        and not clean_hits
        and bool(param_drift)
        and not param_clean
    )
    print(
        "self-test: "
        f"business-leak={bool(leak_hits)} reduce-call={bool(reduce_hits)} "
        f"event-not-generated={bool(drift_hits)} clean-passed={not clean_hits} "
        f"param-symbol-red={bool(param_drift)} param-symbol-clean={not param_clean}"
    )
    for msg in (*leak_hits, *reduce_hits, *drift_hits, *param_drift):
        print(f"  expected-red -> {msg}")
    print("self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="run built-in fixtures")
    parser.add_argument("--root", default="desktop/web/src", type=Path)
    parser.add_argument("--generated-symbol", default=GENERATED_EVENT_SYMBOL, help="codegen'd envelope type name (OPT-10)")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    if not args.root.exists():
        print(f"fail-on-empty: scan target {args.root} does not exist", file=sys.stderr)
        return 2
    violations, scanned = check(args.root, args.generated_symbol)
    if scanned == 0:
        print(f"fail-on-empty: scanned 0 TS sources under {args.root}", file=sys.stderr)
        return 2
    for msg in violations:
        print(msg)
    print(f"thin-client guard: {scanned} files scanned, {len(violations)} violation(s)")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
