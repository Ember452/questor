#!/usr/bin/env python3
"""G-L11 projection payload whitelist guard (ADR-0027; DESIGN §7/§9/§15; HARD C13/C14/C15/C18).

``observability/projection.py`` turns an ``Envelope`` into a log line. Its whole safety property is
that it reads **only** a small static whitelist of scalar keys out of ``env.data`` — everything else
(prompt text, tool arguments, tool results, memory bodies) must never reach the log file.

The design promised a *mechanical* guard ("加键即红"). Auditing blade-2 (Issue #134) found none:
adding a sensitive key to ``_DATA_KEYS`` kept all 527 tests and all existing guards green. This
script closes that gap with two independent checks:

- **(a) inline reads**: any string literal used to index / ``.get()`` data in the file must appear in
  the static whitelist constants. Reading ``data["prompt"]`` directly (bypassing the constant) is red.
- **(b) whitelist contents**: the whitelist constants themselves must not intersect a sensitive-key
  deny list. Widening the whitelist with ``arguments`` / ``result`` / ``text`` … is red.

(a) alone is not enough: it only forces keys to be *named in the constant*, which a motivated change
satisfies by editing the constant. (b) is what makes the zero-plaintext policy machine-enforced.

Usage:
    uv run python scripts/check_projection_whitelist.py             # scan the real tree
    uv run python scripts/check_projection_whitelist.py --self-test # prove it can go red
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

#: The adapter file that is allowed to touch Envelope payloads.
TARGET = "observability/projection.py"

#: Tuple-valued whitelist constants to extract (their literal string elements are the allowed keys).
_TUPLE_KEYS = ("_DATA_KEYS", "_ERROR_SUB_KEYS")
#: String-valued whitelist constant (the container key itself, e.g. ``data["error"]``).
_STR_KEYS = ("_ERROR_CONTAINER_KEY",)

#: Keys that must NEVER be logged, in any form — these carry user/model payload or credentials.
#: 为什么单列一份禁词：投影的白名单是"允许读什么"，而真正的红线是"绝不读什么"。只查前者，扩一次
#: 白名单就能旁路整个政策（Issue #134 的实测：把 ``arguments`` 加进 ``_DATA_KEYS``，全量测试仍绿）。
DENY_KEYS: frozenset[str] = frozenset(
    {
        "prompt",
        "prompts",
        "text",
        "delta",
        "content",
        "contents",
        "messages",
        "context_items",
        "arguments",
        "args",
        "input",
        "result",
        "results",
        "output",
        "outputs",
        "stdout",
        "stderr",
        "body",
        "raw",
        "payload",
        "response",
        "completion",
        "state_digest",
        "digest",
        "snapshot",
        "api_key",
        "apikey",
        "token",
        "secret",
        "password",
        "tool_result",
        "tool_output",
    }
)


def _literal_tuple_values(node: ast.AST) -> list[str]:
    """取一个 AST 节点里的字面量字符串元素（tuple/list 均可），非字面量忽略。"""
    if isinstance(node, (ast.Tuple, ast.List)):
        return [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return []


def _literal_str_value(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _read_key_literals(tree: ast.AST) -> list[tuple[int, str]]:
    """收集所有"按键**读**数据"的字面量键：``x["k"]`` 下标与 ``x.get("k")`` 首参。

    作为赋值目标的 ``out["error_message"] = ...``（ctx=Store）不算读——它写的是自己构造的 fields
    键名，不是从 ``env.data`` 里取业载荷。
    """
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and not isinstance(node.ctx, ast.Store):
            if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                found.append((node.lineno, node.slice.value))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.append((first.lineno, first.value))
    return found


def _assigned_constants(tree: ast.AST) -> dict[str, ast.AST]:
    """收集本文件 ``名字 -> 字面量值节点`` 的赋值（含 ``x: tuple[...] = (...)`` 这种带注解写法）。"""
    out: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            out[node.targets[0].id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            out[node.target.id] = node.value
    return out


def scan_source(source: str, path: str) -> list[str]:
    """Return G-L11 violations for one projection file's source."""
    tree = ast.parse(source)
    constants = _assigned_constants(tree)

    allowed: set[str] = set()
    for const_name, val_node in constants.items():
        if const_name in _TUPLE_KEYS:
            allowed.update(_literal_tuple_values(val_node))
        elif const_name in _STR_KEYS:
            single = _literal_str_value(val_node)
            if single is not None:
                allowed.add(single)

    violations: list[str] = []
    if not allowed:
        violations.append(f"{path}:1: no projection whitelist constants found (guard scope silently shrank: need {'/'.join(_TUPLE_KEYS)})")
        return violations

    # (a) 每一个内联读键都必须出现在静态白名单常量里。
    for lineno, key in _read_key_literals(tree):
        if key not in allowed:
            violations.append(f"{path}:{lineno}: reads payload key '{key}' that is not in the static whitelist (G-L11: add it to _DATA_KEYS and justify it)")

    # (b) 白名单本身不得含敏感键。
    for const_name, val_node in constants.items():
        if const_name in _TUPLE_KEYS:
            keys = _literal_tuple_values(val_node)
        elif const_name in _STR_KEYS:
            keys = [v for v in [_literal_str_value(val_node)] if v]
        else:
            continue
        for key in keys:
            if key.lower() in DENY_KEYS:
                violations.append(f"{path}:{getattr(val_node, 'lineno', '?')}: whitelist '{const_name}' contains denied payload key '{key}' (zero-plaintext policy D4)")

    return violations


def check(root: Path) -> tuple[list[str], int]:
    """Scan the projection file under ``root``; missing file counts as a violation (fail-on-empty)."""
    file = root / TARGET
    if not file.exists():
        return [f"fail-on-empty: '{TARGET}' not found under {root} (guard scope silently shrank)"], 0
    return scan_source(file.read_text(encoding="utf-8"), str(file)), 1


def self_test() -> int:
    """植入三类判例：内联读白名单外的键、白名单里加敏感键、正常白名单放行。"""
    inline_offlist = (
        '_DATA_KEYS: tuple[str, ...] = ("status",)\n'
        "def f(data):\n"
        '    return data["prompt"]\n'
    )
    whitelist_widened = (
        '_DATA_KEYS: tuple[str, ...] = ("status", "arguments")\n'
        "def f(data):\n"
        '    return data["status"]\n'
    )
    ok_case = (
        '_DATA_KEYS: tuple[str, ...] = ("status", "exit_reason", "name", "tool_use_id", "gseq", "message", "reason", "expected", "current")\n'
        '_ERROR_SUB_KEYS: tuple[str, ...] = ("code", "message")\n'
        '_ERROR_CONTAINER_KEY = "error"\n'
        "def f(data):\n"
        '    out = {}\n'
        '    for k in _DATA_KEYS:\n'
        "        if k in data:\n"
        "            out[k] = data[k]\n"
        '    err = data.get(_ERROR_CONTAINER_KEY)\n'
        '    if err and "message" in err:\n'
        '        out["error_message"] = err["message"]\n'
        "    return out\n"
    )

    red_inline = [m for m in scan_source(inline_offlist, "projection.py") if "not in the static whitelist" in m]
    red_widened = [m for m in scan_source(whitelist_widened, "projection.py") if "denied payload key" in m]
    ok_clean = scan_source(ok_case, "projection.py")

    ok = bool(red_inline) and bool(red_widened) and not ok_clean
    print(f"self-test: inline-offlist={bool(red_inline)} whitelist-denied={bool(red_widened)} clean-passed={not ok_clean}")
    for msg in (*red_inline, *red_widened):
        print(f"  expected-red -> {msg}")
    for msg in ok_clean:
        print(f"  UNEXPECTED   -> {msg}")
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
    if scanned == 0:
        print("projection whitelist: FAIL (target file not found)", file=sys.stderr)
        return 2
    if violations:
        return 1
    print(f"projection whitelist: {TARGET} payload reads are all inside the static whitelist (G-L11)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
