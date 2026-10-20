#!/usr/bin/env python3
"""Desktop CSP / capabilities lock (Phase 7 T9; HARD C14/C17; ADR-0007).

The desktop shell must be a thin client pointed ONLY at the loopback sidecar. If the Tauri CSP or
granted capabilities ever widen to remote origins / inline scripts / fs / shell, that reopens exactly
the attack surface the process-boundary + thin-client rules close. Machine-enforce it, self-testable.

Scans ``desktop/src-tauri/tauri.conf.json`` (app.security.csp) + ``desktop/src-tauri/capabilities/*.json``:
- CSP must exist; ``script-src`` must NOT allow 'unsafe-inline'; ``object-src`` must be 'none';
- ``connect-src`` may only reference 'self' + loopback (127.0.0.1/localhost) — NO '*' and NO remote origin;
- capabilities must not grant fs / shell / http / dialog plugin permissions (thin client needs none).
- fail-on-empty: missing tauri.conf.json = misconfiguration, not a pass.

Usage:
    uv run python scripts/check_desktop_csp.py
    uv run python scripts/check_desktop_csp.py --self-test
形状参照 GenericAgent 的前端安全契约测试（改造思路、不标 provenance）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_TAURI_CONF = Path("desktop/src-tauri/tauri.conf.json")
_CAPS_DIR = Path("desktop/src-tauri/capabilities")
# 薄客户端不应拿的能力（正则匹配 permission 标识里的插件域）。
_FORBIDDEN_CAPS = re.compile(r"\b(fs|shell|http|dialog|notification)\b", re.IGNORECASE)


def _violations_for(conf_text: str, caps_texts: list[str]) -> list[str]:
    v: list[str] = []
    try:
        conf = json.loads(conf_text)
    except json.JSONDecodeError as exc:
        return [f"tauri.conf.json is not valid JSON: {exc}"]
    csp = ((conf.get("app") or {}).get("security") or {}).get("csp")
    if not csp:
        v.append("tauri.conf.json: app.security.csp missing (thin client must lock CSP)")
    else:
        # CSP 可能是字符串或按指令的 dict；统一成指令->值串。
        directives: dict[str, str] = {}
        if isinstance(csp, str):
            for part in csp.split(";"):
                part = part.strip()
                if not part:
                    continue
                k, _, rest = part.partition(" ")
                directives[k.lower()] = rest
        script = directives.get("script-src", "")
        if "'unsafe-inline'" in script:
            v.append("CSP script-src allows 'unsafe-inline' (XSS sink in shell)")
        obj = directives.get("object-src")
        if obj != "'none'":
            v.append(f"CSP object-src must be 'none', got {obj!r}")
        connect = directives.get("connect-src", "")
        for token in connect.split():
            t = token.strip().lower()
            if t in {"'self'", "http://127.0.0.1:*", "http://localhost:*", "http://127.0.0.1:*/*", "ws://127.0.0.1:*", "ws://localhost:*"}:
                continue
            if t == "*" or t.endswith("://*") or ".*" in t and "127.0.0.1" not in t and "localhost" not in t:
                v.append(f"CSP connect-src allows wildcard/remote origin {token!r} (shell must be loopback-only)")
            elif re.match(r"^[a-z]+://", t) and not re.match(r"^https?://(127\.0\.0\.1|localhost)(:|\*|/|$)", t):
                v.append(f"CSP connect-src references remote origin {token!r} (no network egress from thin client)")
    for text in caps_texts:
        try:
            caps = json.loads(text)
        except json.JSONDecodeError as exc:
            v.append(f"capabilities JSON invalid: {exc}")
            continue
        perms = caps.get("permissions", [])
        for p in perms:
            pid = p if isinstance(p, str) else (p.get("identifier", "") if isinstance(p, dict) else "")
            if _FORBIDDEN_CAPS.search(pid):
                v.append(f"capabilities grant forbidden plugin permission {pid!r} (thin client needs fs/shell/http = none)")
    return v


def check(conf_path: Path = _TAURI_CONF, caps_dir: Path = _CAPS_DIR) -> tuple[list[str], bool]:
    """扫描壳配置（OPT-10：目标路径可参数化，默认仍是现 Tauri 布局）。"""
    if not conf_path.exists():
        return [f"fail-on-empty: {conf_path} not found"], False
    caps_texts: list[str] = []
    if caps_dir.exists():
        caps_texts = [p.read_text(encoding="utf-8") for p in sorted(caps_dir.glob("*.json"))]
    else:
        return [f"fail-on-empty: no capabilities dir at {caps_dir}"], False
    return _violations_for(conf_path.read_text(encoding="utf-8"), caps_texts), True


# --- self-test fixtures -------------------------------------------------------
_GOOD_CONF = json.dumps({"app": {"security": {"csp": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; object-src 'none'; connect-src 'self' http://127.0.0.1:* http://localhost:*"}}})
_GOOD_CAPS = json.dumps({"permissions": []})
_BAD_INLINE = json.dumps({"app": {"security": {"csp": "script-src 'self' 'unsafe-inline'; object-src 'none'; connect-src 'self'"}}})
_BAD_WILD = json.dumps({"app": {"security": {"csp": "script-src 'self'; object-src 'none'; connect-src 'self' *"}}})
_BAD_OBJ = json.dumps({"app": {"security": {"csp": "script-src 'self'; connect-src 'self'"}}})
_BAD_REMOTE = json.dumps({"app": {"security": {"csp": "script-src 'self'; object-src 'none'; connect-src 'self' https://evil.example.com"}}})
_BAD_CAPS = json.dumps({"permissions": ["fs:allow-read", "shell:allow-execute"]})


def self_test() -> int:
    good = _violations_for(_GOOD_CONF, [_GOOD_CAPS])
    bad_inline = _violations_for(_BAD_INLINE, [_GOOD_CAPS])
    bad_wild = _violations_for(_BAD_WILD, [_GOOD_CAPS])
    bad_obj = _violations_for(_BAD_OBJ, [_GOOD_CAPS])
    bad_remote = _violations_for(_BAD_REMOTE, [_GOOD_CAPS])
    bad_caps = _violations_for(_GOOD_CONF, [_BAD_CAPS])
    ok = (not good) and bad_inline and bad_wild and bad_obj and bad_remote and bad_caps
    print(f"self-test: clean-passed={not good} inline-red={bool(bad_inline)} wildcard-red={bool(bad_wild)} object-src-red={bool(bad_obj)} remote-red={bool(bad_remote)} caps-red={bool(bad_caps)}")
    for msg in (*bad_inline, *bad_wild, *bad_obj, *bad_remote, *bad_caps):
        print(f"  expected-red -> {msg}")
    print("self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--tauri-conf", default=_TAURI_CONF, type=Path, help="shell config holding app.security.csp (OPT-10)")
    ap.add_argument("--caps-dir", default=_CAPS_DIR, type=Path, help="directory of capability JSONs (OPT-10)")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    violations, found = check(args.tauri_conf, args.caps_dir)
    if not found:
        for m in violations:
            print(m, file=sys.stderr)
        return 2
    for m in violations:
        print(m)
    print(f"desktop CSP/capabilities lock: {len(violations)} violation(s)")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
