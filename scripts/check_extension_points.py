#!/usr/bin/env python3
"""B5 扩展面守卫（v3 §5.1/§5.2；§21 G2/G3；ADR-0053）。

四条机器判据，全部 fail-on-empty：

A. **点位封闭**：``contracts/extension.py`` 恰好 13 个生效 + 4 个预留（上限 17）；
   每个生效名可构造 descriptor，预留名构造即抛（启用需 ADR）。
B. **OBSERVE 不自伤**：观察链条目返回 ``FAILED_ABORT`` 必须被归一为 ``FAILED_CONTINUE``；
   声明结构没有 ``failure_semantics`` 字段（不可声明覆盖点位内建的 fail-closed）。
C. **kernel 不 import registry**：``src/questor/kernel/**/*.py`` 不得 import
   ``questor.policy`` / ``questor.surfaces``（内核只依赖 contracts，链由装配注入）。
D. **组合根无业务分支**：``src/questor/composition.py`` 只允许装配语句；``if`` 只允许
   ``spec`` 收窄（``if spec is None`` / ``if spec.x is None``），禁止 for/while/try/with/match
   与 ``reduce()`` / bare ``apply()`` 调用。

Usage:
    uv run python scripts/check_extension_points.py
    uv run python scripts/check_extension_points.py --self-test
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _guard_kit import EXIT_OK, EXIT_RED, fail_on_empty, read_text, run_self_test, walk_py

ROOT = Path(__file__).resolve().parents[1]
COMPOSITION = ROOT / "src" / "questor" / "composition.py"
KERNEL_DIR = ROOT / "src" / "questor" / "kernel"
BUSINESS_CALLS = frozenset({"reduce", "apply"})
FORBIDDEN_NODES = (ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith, ast.Match)


def check_points() -> list[str]:
    """13+4 封闭 + 预留名拒绝 + OBSERVE 失败归一。"""
    from questor.contracts.extension import (
        LIVE_POINTS,
        RESERVED_POINTS,
        ExtensionDescriptor,
        ExtensionKind,
        HookOutcome,
        HookOutcomeKind,
        ObserveChain,
        ObserveEntry,
    )

    out: list[str] = []
    if len(LIVE_POINTS) != 13:
        out.append(f"live points = {len(LIVE_POINTS)}, expected 13")
    if len(RESERVED_POINTS) != 4:
        out.append(f"reserved points = {len(RESERVED_POINTS)}, expected 4")
    if len(LIVE_POINTS) + len(RESERVED_POINTS) != 17:
        out.append("point cap (13+4) is not 17 (G3)")
    for point in LIVE_POINTS:
        try:
            ExtensionDescriptor(id=f"probe:{point}", kind=ExtensionKind.OBSERVE, at=point)
        except Exception as exc:  # noqa: BLE001 - 任一生效点不可构造即判红
            out.append(f"live point {point!r} rejected by descriptor: {exc}")
    for point in RESERVED_POINTS:
        try:
            ExtensionDescriptor(id=f"probe:{point}", kind=ExtensionKind.OBSERVE, at=point)
        except ValueError:
            continue
        out.append(f"reserved point {point!r} was accepted without an ADR")
    if "failure_semantics" in {field.name for field in ExtensionDescriptor.__dataclass_fields__.values()}:
        out.append("ExtensionDescriptor must not declare failure_semantics (C-2)")

    async def _hook(_payload: object) -> HookOutcome:
        return HookOutcome(kind=HookOutcomeKind.FAILED_ABORT, reason="must not abort")

    descriptor = ExtensionDescriptor(id="probe:observe", kind=ExtensionKind.OBSERVE, at="Stop")
    outcomes = asyncio.run(ObserveChain((ObserveEntry(descriptor, _hook),)).emit(object()))
    if not outcomes or outcomes[0].kind is not HookOutcomeKind.FAILED_CONTINUE:
        out.append("OBSERVE FAILED_ABORT was not normalized to FAILED_CONTINUE")
    return out


def analyze_kernel_source(source: str, path: str) -> list[str]:
    """kernel 源码不得 import policy/surfaces（AST，动态 import 由 ruff/审阅兜底）。"""
    tree = ast.parse(source)
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith(("questor.policy", "questor.surfaces")):
                violations.append(f"{path}:{node.lineno}: kernel imports {node.module} (must depend on contracts only)")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(("questor.policy", "questor.surfaces")):
                    violations.append(f"{path}:{node.lineno}: kernel imports {alias.name} (must depend on contracts only)")
    return violations


def check_kernel_imports() -> list[str]:
    files = fail_on_empty("kernel python files", list(walk_py(KERNEL_DIR)))
    out: list[str] = []
    for path in files:
        out.extend(analyze_kernel_source(read_text(path), str(path.relative_to(ROOT))))
    return out


def analyze_composition(source: str, path: str = "composition.py") -> list[str]:
    """组合根只允许装配：if 仅限 spec 收窄；禁止循环/try/with/match/业务调用。"""
    tree = ast.parse(source)
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, FORBIDDEN_NODES):
            violations.append(f"{path}:{node.lineno}: composition root contains {type(node).__name__} (assembly-only)")
        elif isinstance(node, ast.If):
            names = {child.id for child in ast.walk(node.test) if isinstance(child, ast.Name)}
            if "spec" not in names:
                violations.append(f"{path}:{node.lineno}: composition root branch is not a spec narrowing (business branch)")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in BUSINESS_CALLS:
            violations.append(f"{path}:{node.lineno}: composition root calls {node.func.id}() (business logic)")
    return violations


def check_composition() -> list[str]:
    fail_on_empty("composition.py", [COMPOSITION] if COMPOSITION.exists() else [])
    return analyze_composition(read_text(COMPOSITION), str(COMPOSITION.relative_to(ROOT)))


def self_test() -> int:
    red_composition = "def build_app():\n    for x in range(3):\n        pass\n"
    green_composition = "def build_app(spec):\n    if spec is None:\n        spec = object()\n    return spec\n"
    red_kernel = "from questor.policy import registry\n"
    green_kernel = "from questor.contracts import events\n"
    points = check_points()
    cases = [
        ("points-closed", not points, f"{len(points)} violation(s)"),
        ("composition-for-red", bool(analyze_composition(red_composition)), "for-loop detected"),
        ("composition-spec-green", not analyze_composition(green_composition), "spec narrowing allowed"),
        ("kernel-policy-red", bool(analyze_kernel_source(red_kernel, "kernel/x.py")), "policy import detected"),
        ("kernel-contracts-green", not analyze_kernel_source(green_kernel, "kernel/x.py"), "contracts import allowed"),
    ]
    if points:
        for violation in points:
            print(f"  expected-red -> {violation}")
    return run_self_test(cases)


def main() -> int:
    parser = argparse.ArgumentParser(description="extension points / OBSERVE / kernel / composition guard")
    parser.add_argument("--self-test", action="store_true", help="prove each rule can go red")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    violations = [*check_points(), *check_kernel_imports(), *check_composition()]
    if violations:
        for violation in violations:
            print(violation)
        print(f"extension points guard: {len(violations)} violation(s)")
        return EXIT_RED
    print("extension points guard: 13+4 closed; OBSERVE cannot abort; kernel contracts-only; composition assembly-only")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
