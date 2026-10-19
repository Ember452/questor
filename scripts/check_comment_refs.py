#!/usr/bin/env python3
"""Dangling comment-reference guard (红线机守；防止"注释引用已删/改名符号")。

审计发现：`capability_floor.py` 注释长期引用早已删除的 `_FULL_BACKENDS`，是这类缺陷的原型——
代码改了、注释里的**私有符号名**没跟着改，读者被指向一个不存在的实体。这类回归用肉眼难扫，
故机守之。

规则（刻意收紧以压误报，只作 CI 绿门用）：
- 只判定**下划线开头的 snake 符号**（``_FULL_BACKENDS`` 这类私有名）出现在 ``src/questor`` 的
  注释或 docstring 里；CamelCase 散文名词、示例值、外部常量不判（噪声大）。
- "存在集"= ``src/questor``+``scripts``+``tests`` 的 AST 标识符（Name/attr/def/class/arg/alias/Global）
  ∪ 模块/文件/目录名 ∪ **非 docstring 字符串字面量**里的词（覆盖 SQL 表名、log_fields 键、正则等）。
- **历史引用豁免**：若同一注释/docstring 文本含"原名/旧名/曾用名/前名/取代旧/renamed/formerly/
  previously/former"，视为刻意引用旧名，不判红。

Usage:
    uv run python scripts/check_comment_refs.py            # 扫描交付代码，发现悬空私有引用即红
    uv run python scripts/check_comment_refs.py --self-test # 证伪：注入一个必不存在的私有符号应被抓
"""

from __future__ import annotations

import argparse
import ast
import io
import re
import sys
import tokenize
from pathlib import Path

#: 扫描（取注释/docstring）的范围：交付代码。
SCAN_ROOT = Path("src/questor")
#: 定义"符号是否存在"的范围：交付代码 + 守卫脚本 + 测试。
DEFINE_ROOTS: tuple[str, ...] = ("src/questor", "scripts", "tests")

#: 下划线开头的 snake 私有符号（长度 >=4）。负向后视排除 `*_delta`（通配）与 `litellm._logging`（外部属性路径）。
_PRIVATE = re.compile(r"(?<![\w.*])_[A-Za-z][A-Za-z0-9_]{2,}\b")
#: 历史/改名引用豁免关键词——含之则视为刻意提旧名，不判悬空。
_RENAME_HINT = re.compile(
    r"原名|旧名|曾用名|曾命名|旧写法|旧实现|旧代码|前名|前该|名为|改为|改名|更名为|取代|曾|renamed|formerly|previously|former|the old|pre-A",
    re.IGNORECASE,
)
_TOKEN = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")


def _iter_py(root: str):
    base = Path(root)
    if base.exists():
        yield from base.rglob("*.py")


def module_and_dir_names() -> set[str]:
    """模块/文件/目录名并入"存在集"，避免 `store_memory_sqlite`、`_win_job` 这类正当引用被误判。"""
    names: set[str] = set()
    for root in DEFINE_ROOTS:
        base = Path(root)
        for p in _iter_py(root):
            names.add(p.stem)
            for part in p.relative_to(base).parts:
                names.add(part.replace(".py", ""))
        if base.exists():
            for d in base.rglob("*"):
                if d.is_dir():
                    names.add(d.name)
    return names


def defined_symbols() -> set[str]:
    """真实代码里定义的标识符 + 非 docstring 字符串里的词（视为"存在"）。"""
    found: set[str] = set()
    for root in DEFINE_ROOTS:
        for py in _iter_py(root):
            src = py.read_text(encoding="utf-8")
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            doc_ids = _docstring_ids(tree)
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    found.add(node.id)
                elif isinstance(node, ast.Attribute):
                    found.add(node.attr)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    found.add(node.name)
                elif isinstance(node, ast.arg):
                    found.add(node.arg)
                elif isinstance(node, ast.keyword) and node.arg:
                    found.add(node.arg)
                elif isinstance(node, ast.Global):
                    found.update(node.names)
                elif isinstance(node, ast.alias):
                    found.add((node.asname or node.name).split(".")[0])
                elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in doc_ids:
                    found.update(_TOKEN.findall(node.value))
    return found


def _docstring_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and body:
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                ids.add(id(first.value))
    return ids


def _docstring_texts(tree: ast.AST) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and body:
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                out.append((first.value.lineno, first.value.value))
    return out


def scan_source(text: str, path: str, known: set[str]) -> list[str]:
    """返回该文件里"注释/docstring 引用了不存在私有符号"的告警（豁免历史引用）。"""
    violations: list[str] = []
    # 注释行（逐行：同一行的历史豁免有效）
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError):
        toks = []
    for t in toks:
        if t.type != tokenize.COMMENT:
            continue
        if _RENAME_HINT.search(t.string):
            continue
        for sym in _PRIVATE.findall(t.string):
            if sym not in known:
                violations.append(f"{path}:{t.start[0]}: comment references undefined private symbol '{sym}'")
    # docstring（整段做历史豁免上下文）
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return violations
    for start, doc in _docstring_texts(tree):
        if _RENAME_HINT.search(doc):
            continue
        for j, line in enumerate(doc.splitlines()):
            for sym in _PRIVATE.findall(line):
                if sym not in known:
                    violations.append(f"{path}:{start + j}: docstring references undefined private symbol '{sym}'")
    return violations


def check() -> tuple[list[str], int]:
    known = defined_symbols() | module_and_dir_names()
    violations: list[str] = []
    scanned = 0
    for py in sorted(SCAN_ROOT.rglob("*.py")):
        rel = str(py.relative_to(SCAN_ROOT)).replace("\\", "/")
        text = py.read_text(encoding="utf-8")
        scanned += 1
        violations += scan_source(text, rel, known)
    if scanned == 0:  # fail-on-empty
        return [f"fail-on-empty: no sources found under {SCAN_ROOT}"], 0
    return violations, scanned


def self_test() -> int:
    known = defined_symbols() | module_and_dir_names()
    # 分段拼接，使整词字面不出现在任何源文件（否则被 defined_symbols 当成"存在"而漏判）。
    probe = "_Dang" + "ling_GuardProbeZz9Q"  # 运行期拼接（非相邻字面量），防止解析期折叠后被 defined_symbols 收成"存在"
    # 1) 注入一个几乎不可能存在的私有符号 -> 必须被抓（假阴性检验）
    bad = f"# 详见 {probe} 的说明\n"
    bad_hits = scan_source(bad, "<bad>", known)
    # 2) 历史引用（含"原名"）-> 必须豁免（假阳性检验）
    hist = f"# 原名 {probe}，ADR-9999 改名\n"
    hist_hits = scan_source(hist, "<hist>", known)
    # 3) 真实私有符号（本仓确有的 _docstring_ids）-> 不判
    ok = "# 走 _docstring_ids 取 docstring\n"
    ok_hits = scan_source(ok, "<ok>", known)
    passed = bool(bad_hits) and not hist_hits and not ok_hits
    print(f"self-test: dangling-caught={bool(bad_hits)} rename-exempted={not hist_hits} real-symbol-passed={not ok_hits}")
    for m in bad_hits:
        print(f"  expected-red -> {m}")
    print("self-test:", "PASS" if passed else "FAIL")
    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    violations, _ = check()
    for msg in violations:
        print(msg, file=sys.stderr)
    if violations:
        return 1
    print("comment-ref guard: no dangling private-symbol references in shipped-code comments/docstrings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
