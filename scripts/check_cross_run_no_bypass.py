#!/usr/bin/env python3
"""G-P8 cross-run no-bypass guard (ADR-0038; HARD C2/C5/C16).

跨 run 状态变更只有一条合法路：`Command → 目标 run 的 inbox → reduce`。任何代码"替别的 run 直接
改 Run/controller.run"就是第二写者（撕裂单写者/回放/审计）。`Run` 是 frozen dataclass（`run.field = x`
运行时即抛），所以真正的绕过形状是 **`<foreign_controller>.run = <new>`** 赋值——只允许出现在两处合法点：

  - `kernel/run_control.py`：`RunController.__init__` 的 `self.run = run`（构造，非跨 run）
  - `kernel/loop.py`：驱动某 run 的**唯一** loop 重绑它**自己的** `controller.run`（单写者的合法写点）

其余任何文件出现 `.run =` 赋值即判红。fail-on-empty：至少要扫到文件、且 allowlist 内确有命中（证明
正则没静默失配）。`--self-test` 证明能判红（植入 foreign `.run =`）且不误伤合法点。

Usage:
    uv run python scripts/check_cross_run_no_bypass.py
    uv run python scripts/check_cross_run_no_bypass.py --self-test
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_ASSIGN = re.compile(r"\.run\s*=(?!=)")
#: 允许 `.run =` 的合法点（自身 controller 单写者 / 构造），按 posix 相对路径后缀匹配。
_ALLOWED_SUFFIXES = ("kernel/loop.py", "kernel/run_control.py")
#: 记忆写回只允许在 kernel 的消费点（loop 的 WriteMemory / settle 的 session 写），surface 不得旁路。
_MEMORY_WRITE = re.compile(r"\.memory_store\.write\(")
_MEMORY_WRITE_ALLOWED = ("kernel/loop.py", "kernel/settle.py")


def scan_source(source: str, rel_path: str) -> list[str]:
    """返回单个源文件的违规行（allowlist 内的合法写点跳过）。"""
    violations: list[str] = []
    normalized = rel_path.replace("\\", "/")
    allowed = any(normalized.endswith(suffix) for suffix in _ALLOWED_SUFFIXES)
    memory_allowed = any(normalized.endswith(suffix) for suffix in _MEMORY_WRITE_ALLOWED)
    for lineno, line in enumerate(source.splitlines(), 1):
        if _ASSIGN.search(line) and not allowed:
            violations.append(
                f"{rel_path}:{lineno}: cross-run/foreign `.run=` assignment (must go via Command→inbox→reduce): {line.strip()}"
            )
        if _MEMORY_WRITE.search(line) and not memory_allowed:
            violations.append(
                f"{rel_path}:{lineno}: memory write outside kernel consumption points (surface bypass): {line.strip()}"
            )
    return violations


def check(root: Path) -> list[str]:
    """扫全树找非法 `.run =`；fail-on-empty：无 py 文件或 allowlist 内零命中都算配置错误。"""
    files = sorted(root.rglob("*.py"))
    if not files:
        return [f"fail-on-empty: no python files under {root} (guard scope silently shrank)"]
    violations: list[str] = []
    allowed_hits = 0
    for file in files:
        rel = file.relative_to(root).as_posix()
        source = file.read_text(encoding="utf-8")
        if any(rel.endswith(suffix) for suffix in _ALLOWED_SUFFIXES):
            allowed_hits += len(_ASSIGN.findall(source))
        violations.extend(scan_source(source, rel))
    if allowed_hits == 0:
        violations.append(f"fail-on-empty: no `.run=` found even in {'/'.join(_ALLOWED_SUFFIXES)} — regex or layout changed")
    return violations


def self_test() -> int:
    """植入 foreign `.run=` 必判红；合法 loop.py 写点不误伤。"""
    foreign = scan_source("def f(c):\n    c.run = other_run\n", "surfaces/subagent_orchestrator.py")
    legal = scan_source("        controller.run = run\n", "src/questor/kernel/loop.py")
    memory_bypass = scan_source("        await self.memory_store.write(payload)\n", "surfaces/cli.py")
    memory_legal = scan_source("        await self.memory_store.write(payload)\n", "src/questor/kernel/settle.py")
    ok = bool(foreign) and not legal and bool(memory_bypass) and not memory_legal
    print(f"self-test: foreign-caught={bool(foreign)} legal-allowed={not legal} memory-bypass-caught={bool(memory_bypass)} memory-legal={not memory_legal}")
    for msg in foreign + memory_bypass:
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
    violations = check(args.root)
    for msg in violations:
        print(msg, file=sys.stderr)
    if violations:
        return 1
    print("cross-run no-bypass: no foreign `.run=` writes outside the sanctioned single-writer sites (ADR-0038)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
