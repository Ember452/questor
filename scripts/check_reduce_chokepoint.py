#!/usr/bin/env python3
"""Reduce 咽喉守卫（v3 §4.1 / 刀 B0；HARD C2/C5/C15）。

只保证"入口唯一"不够（AST 禁裸调 reduce），还要保证**形态唯一**。本守卫用 AST 断言两件事：

  ① ``reduce(`` 只允许出现在 ``state/transition.py``（调用）与 ``state/reduce.py``（定义本体）；
     ``from questor.state.reduce import reduce`` 同样只允许在这两处（否则 ``as _r`` 之类别名
     就能绕开第一条）。
  ② ``event_log.append`` 的载荷只可能来自 ``state/persist_form.py`` 的 :func:`durable_form`
     ——即"什么进事实流、以什么形态进"只有一处判断；不允许在 bus 里另造一份。

每条都带 ``--self-test`` 判红证明（在 loop.py 直调 reduce、inline 拼 append 载荷），
并用 ``_guard_kit`` 的 fail-on-empty 保证扫描面没有静默缩成 0。

退出码（沿用 ``scripts/_guard_kit`` 约定）：
    0 = 绿；1 = 有违规；2 = 参数/自身错误（关键文件缺失、扫描为空）。

Usage:
    uv run python scripts/check_reduce_chokepoint.py
    uv run python scripts/check_reduce_chokepoint.py --self-test
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _guard_kit import EXIT_OK, fail_on_empty, read_text, run_self_test, walk_py

#: 仓库根（本文件在 `<root>/scripts/` 下）。
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "questor"

#: 唯一允许 ``reduce(`` 调用的文件。
TRANSITION = "state/transition.py"
#: ``reduce`` 的定义本体（不得在别处调用它）。
REDUCE_DEF = "state/reduce.py"
#: 唯一写 event_log 的文件（bus 持久化）。
EVENTS = "kernel/events.py"

#: 形态唯一来源。
DURABLE_FORM = "durable_form"


def _role(path: str) -> str:
    """按文件尾部路径判定角色（真实扫描与 self-test 的合成路径共用同一口径）。"""
    norm = path.replace("\\", "/")
    if norm.endswith(TRANSITION):
        return "transition"
    if norm.endswith(REDUCE_DEF):
        return "reduce-def"
    if norm.endswith(EVENTS):
        return "events"
    return "other"


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _durable_names(func: ast.AST) -> set[str]:
    """收集函数内 ``x = durable_form(...)`` 的绑定名（载荷唯一合法来源）。"""
    names: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Assign):
            value = node.value
            targets: list[ast.expr] = list(node.targets)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            value = node.value
            targets = [node.target]
        else:
            continue
        if isinstance(value, ast.Call) and _call_name(value) == DURABLE_FORM:
            names |= {t.id for t in targets if isinstance(t, ast.Name)}
    return names


def _names_in(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _is_event_log_append(node: ast.Call) -> bool:
    """只认 ``*.store*.append(...)``（event_log 写入）；list 的 ``append`` 不在本守卫范围。"""
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr == "append"):
        return False
    return "store" in ast.unparse(func.value).lower()


def _append_payload_args(call: ast.Call) -> list[ast.expr]:
    """``append(run_id, (row,), **kwargs)`` → 取第二个位置参数（或 ``events=`` 关键字）。"""
    args = list(call.args)
    for kw in call.keywords:
        if kw.arg == "events":
            args.append(kw.value)
    return args[1:2]


def _check_persist_payload(tree: ast.Module, path: str) -> list[str]:
    """②：``append`` 的载荷必须引用 ``durable_form()`` 的返回值。"""
    violations: list[str] = []
    found = 0
    for func in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        durable = _durable_names(func)
        for node in ast.walk(func):
            if not (isinstance(node, ast.Call) and _is_event_log_append(node)):
                continue
            found += 1
            payloads = _append_payload_args(node)
            if not payloads:
                violations.append(f"{path}:{node.lineno}: append() without a payload argument")
                continue
            if not (_names_in(payloads[0]) & durable):
                violations.append(
                    f"{path}:{node.lineno}: event_log.append payload is not derived from {DURABLE_FORM}() "
                    "(durable form must have a single source)"
                )
    if found == 0:
        violations.append(
            f"{path}: fail-on-empty: no event_log.append call found in {EVENTS} "
            "(scan surface silently shrank)"
        )
    return violations


def analyze_source(path: str, source: str) -> list[str]:
    """对单个源文件跑两条 AST 断言；返回违规消息（空 = 绿）。"""
    tree = ast.parse(source)
    role = _role(path)
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node) == "reduce" and role not in {"transition", "reduce-def"}:
            violations.append(
                f"{path}:{node.lineno}: reduce() called outside {TRANSITION} (chokepoint bypass)"
            )
        if (
            isinstance(node, ast.ImportFrom)
            and (node.module or "").endswith("state.reduce")
            and role not in {"transition", "reduce-def"}
            and any(alias.name == "reduce" for alias in node.names)
        ):
            violations.append(
                f"{path}:{node.lineno}: imports reduce outside {TRANSITION} (aliasing would bypass the AST check)"
            )
    if role == "events":
        violations += _check_persist_payload(tree, path)
    return violations


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def check() -> int:
    files = fail_on_empty("python files under src/questor", walk_py(SRC))
    required = {name: ROOT / "src" / "questor" / name for name in (TRANSITION, REDUCE_DEF, EVENTS)}
    missing = [f"{name} (missing)" for name, path in required.items() if not path.exists()]
    if missing:
        print(f"CONFIG: fail-on-empty: chokepoint files missing: {', '.join(missing)}", file=sys.stderr)
        return 2

    violations: list[str] = []
    reduce_calls = 0
    for path in files:
        source = read_text(path)
        violations += analyze_source(_relative(path), source)
        if _role(str(path)) == "transition":
            reduce_calls += sum(
                1
                for node in ast.walk(ast.parse(source))
                if isinstance(node, ast.Call) and _call_name(node) == "reduce"
            )
    if reduce_calls == 0:
        print(f"CONFIG: fail-on-empty: no reduce() call in {TRANSITION} (guard scope silently shrank)", file=sys.stderr)
        return 2

    for msg in violations:
        print(msg)
    print(
        f"reduce chokepoint OK: {len(files)} files scanned, {reduce_calls} reduce() call(s) in {TRANSITION}, "
        "append payloads come from durable_form()"
    )
    return 1 if violations else EXIT_OK


def self_test() -> int:
    """判红证明：在 loop.py 直调 reduce / bus inline 拼载荷都必须被抓到；合法形状必须放行。"""
    loop_bypass = "def drive(run, cmd):\n    return reduce(run, cmd)\n"
    alias_bypass = "from questor.state.reduce import reduce as _r\n"
    transition_ok = "from questor.state.reduce import reduce\n\ndef apply(run, cmd):\n    return reduce(run, cmd)\n"
    events_ok = (
        "def emit(env):\n"
        "    durable = durable_form(env)\n"
        "    if durable is not None:\n"
        "        await self._store.append(durable.run_id, ({'seq': durable.seq},))\n"
    )
    events_inline = "def emit(env):\n    await self._store.append(env.run_id, ({'seq': env.seq},))\n"

    bypass_hits = analyze_source("src/questor/kernel/loop.py", loop_bypass)
    alias_hits = analyze_source("src/questor/kernel/loop.py", alias_bypass)
    transition_hits = analyze_source("src/questor/state/transition.py", transition_ok)
    events_ok_hits = analyze_source("src/questor/kernel/events.py", events_ok)
    events_inline_hits = analyze_source("src/questor/kernel/events.py", events_inline)

    cases = [
        ("loop-direct-reduce", bool(bypass_hits), bypass_hits[0] if bypass_hits else "no hit"),
        ("reduce-alias-import", bool(alias_hits), alias_hits[0] if alias_hits else "no hit"),
        ("transition-allowed", not transition_hits, f"{len(transition_hits)} violation(s)"),
        ("durable-form-payload", not events_ok_hits, f"{len(events_ok_hits)} violation(s)"),
        ("inline-payload", bool(events_inline_hits), events_inline_hits[0] if events_inline_hits else "no hit"),
    ]
    return run_self_test(cases)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="prove the guard can go red")
    args = parser.parse_args()
    return self_test() if args.self_test else check()


if __name__ == "__main__":
    raise SystemExit(main())
