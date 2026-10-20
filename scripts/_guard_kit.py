#!/usr/bin/env python3
"""共用守卫 kit（v3 §21 G2）：遍历 / 读取口径 / self-test 输出 / fail-on-empty / 退出码常量。

**新守卫必须复用本 kit，否则不得入 CI**（§21 G2 原文：「新守卫**必须复用 kit**，否则不得入 CI」）。
理由不是审美：千文件规模下，"各自实现一遍 walker + 各自实现一遍 self-test"是时长炸弹，
而且口径会分叉（同一份仓，两个守卫数出两个文件数）。

刻意只做窄的四件事，不做框架：

1. **遍历口径** `walk_py(root)`：`Path.rglob("*.py")` + 剪枝 `SKIP_DIRS`
   （`__pycache__`/`.venv`/`.ruff_cache`/`build`），**排序后**返回——同一提交在各平台上给出同一序列，
   否则"计数一致"类断言会随机红。
2. **读取口径** `read_text()` / `count_lines()`：一律 UTF-8（`utf-8-sig`，吃 BOM 但不把它算进正文），
   行数一律 `len(splitlines())`——与 v3 §15.6「口径声明：行数 = python `len(read().splitlines())`」对齐。
   （`Measure-Object -Line` 漏计空行，是 §15.5 P4 三个行数全错的病根，不要再用。）
3. **自测口径** `run_self_test(cases)`：逐条 `  [PASS]/[FAIL] <label>: <detail>`，末行 `self-test: PASS|FAIL`，
   返回 `EXIT_OK`/`EXIT_RED`——沿既有守卫（`check_comment_refs`/`check_cross_run_no_bypass`）的 stdout 风格，
   不引入第二种自测输出格式。
4. **空集合口径** `fail_on_empty(name, items)`：空集合**不是**"通过"，是配置错误（退出码 2）。
   守卫"静默失配"是假绿的最大来源（`check_comment_refs` 的 fail-on-empty 注释已自证前科）。

Usage（新守卫照着抄）:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))

    from _guard_kit import EXIT_OK, EXIT_RED, read_text, run_self_test, walk_py

只用标准库。
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

#: 守卫统一退出码（与既有 `scripts/check_*.py` 约定一致；config 错误单列，避免"空扫描=绿"）。
EXIT_OK = 0
EXIT_RED = 1
EXIT_CONFIG = 2

#: 遍历时剪枝的目录名（§21 G2）。命中任一段即整棵跳过。
SKIP_DIRS: frozenset[str] = frozenset({"__pycache__", ".venv", ".ruff_cache", "build"})


def walk_py(root: Path) -> Iterable[Path]:
    """递归遍历 root 下的 `*.py`，剪枝 `SKIP_DIRS`，排序输出（跨平台确定性）。"""
    base = Path(root)
    for path in sorted(base.rglob("*.py")):
        if SKIP_DIRS.intersection(path.parts):
            continue
        yield path


def read_text(p: Path) -> str:
    """统一读取口径：UTF-8（吃掉 BOM，不把 BOM 算进正文）。"""
    return Path(p).read_text(encoding="utf-8-sig")


def count_lines(p: Path) -> int:
    """统一行数口径：`len(read_text(p).splitlines())`（§15.6 口径声明）。"""
    return len(read_text(p).splitlines())


def run_self_test(cases: Sequence[tuple[str, bool, str]]) -> int:
    """跑自测用例并统一输出。

    `cases`：`(label, ok, detail)` 序列。全部 ok → `EXIT_OK`，否则 `EXIT_RED`。
    输出形如::

          [PASS] counts-mutation: 1 expected-red hit
          [FAIL] refs-deletion: 0 expected-red hit
        self-test: FAIL
    """
    all_ok = True
    for label, ok, detail in cases:
        all_ok = all_ok and bool(ok)
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}: {detail}")
    print("self-test:", "PASS" if all_ok else "FAIL")
    return EXIT_OK if all_ok else EXIT_RED


def fail_on_empty(name: str, items: Iterable[object]) -> list[object]:
    """空集合 → 打印 CONFIG 行并以退出码 2 结束；非空 → 物化后返回（便于链式使用）。

    语义：扫描面"静默缩到 0"（路径改了、glob 失配、解析没命中）绝不能表现为绿。
    """
    values = list(items)
    if not values:
        print(f"CONFIG: fail-on-empty: {name} resolved to an empty set (guard scope silently shrank)", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG)
    return values
