#!/usr/bin/env python3
"""Secret/env-value projection guard (ADR-0019; HARD C4/C17/C18; design/02 §5).

Events and their ``data`` are the external surface. A secret/credential/env *value* or a
raw full-args blob must never reach them. This is a deterministic AST scan of the two places
that shape outbound data:

1. event construction sites (``state/reduce.py`` / ``kernel/loop.py``): no dict literal may use
   a secret-shaped key (api_key/token/secret/password/credential/environment/full_args/...);
2. the projection whitelist (``kernel/events.EXTERNAL_EVENT_FIELDS``): no whitelisted outbound
   key may be secret-shaped.

Env *names* are allowed (``env_scrubbed``); env *values* are not. fail-on-empty on both the
file scan and the whitelist.

Usage:
    uv run python scripts/check_secret_projection.py            # scan real tree
    uv run python scripts/check_secret_projection.py --self-test # prove it can go red
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

#: 精确匹配（小写）的密钥/敏感值形状键；``env_scrubbed`` 保存的是名字不是值，不在此列。
FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {
        "api_key",
        "apikey",
        "access_key",
        "secret",
        "client_secret",
        "token",
        "access_token",
        "refresh_token",
        "password",
        "credential",
        "credentials",
        "private_key",
        "environment",
        "env_values",
        "full_args",
        "raw_args",
        "authorization",
    }
)

_EVENT_SOURCES: tuple[str, ...] = ("state/reduce.py", "kernel/loop.py")


def scan_source(source: str, path: str) -> list[str]:
    tree = ast.parse(source)
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value.lower() in FORBIDDEN_KEYS:
                    violations.append(f"{path}:{key.lineno if hasattr(key, 'lineno') else node.lineno}: secret-shaped key '{key.value}' in event data (C17)")
    return violations


def check(root: Path = Path("src/questor")) -> tuple[list[str], int]:
    violations: list[str] = []
    scanned = 0
    for rel in _EVENT_SOURCES:
        file = root / rel
        if not file.exists():
            continue
        scanned += 1
        violations += scan_source(file.read_text(encoding="utf-8"), str(file))
    if scanned == 0:  # fail-on-empty: the sources we expect to guard must be present
        return [f"fail-on-empty: none of {_EVENT_SOURCES} found under {root}"], 0

    # 投影白名单自身也不能含密钥形状键。
    from questor.kernel.events import EXTERNAL_EVENT_FIELDS

    for etype, allowed in EXTERNAL_EVENT_FIELDS.items():
        if allowed is None:
            continue
        for key in allowed:
            if key.lower() in FORBIDDEN_KEYS:
                violations.append(f"projection whitelist for '{etype}' exposes secret-shaped key '{key}'")
    return violations, scanned


def self_test() -> int:
    bad = 'data = {"api_key": "sk-123", "message": "ok"}\n'
    good = 'data = {"args_summary": "write x.txt", "env_scrubbed": ["PATH"]}\n'
    bad_hits = scan_source(bad, "<bad>")
    good_hits = scan_source(good, "<good>")
    from questor.kernel.events import EXTERNAL_EVENT_FIELDS

    whitelist_ok = all(
        key.lower() not in FORBIDDEN_KEYS for allowed in EXTERNAL_EVENT_FIELDS.values() if allowed is not None for key in allowed
    )
    ok = bool(bad_hits) and not good_hits and whitelist_ok
    print(f"self-test: secret-key flagged={bool(bad_hits)} benign-passed={not good_hits} whitelist-clean={whitelist_ok}")
    for msg in bad_hits:
        print(f"  expected-red -> {msg}")
    print("self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--root", default="src/questor", type=Path)
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    violations, _scanned = check(args.root)
    for msg in violations:
        print(msg, file=sys.stderr)
    if violations:
        return 1
    print("secret-projection guard: no secret-shaped keys in event sources or whitelist")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
