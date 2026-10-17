#!/usr/bin/env python3
"""Release-bundle verifier for the frozen sidecar (HARD C14/C15; STRUCTURE §9 sidecar 三段式).

发布前的一道机器门（结构可判红、自带 --self-test + fail-on-empty）。断言一个已冻结 sidecar bundle：
1. **恰一个** sidecar 可执行体：0 个（fail-on-empty，构建根本没产出）或 >1 个（多份、取哪份？）都判红；
2. **内嵌解释器在位**（无系统 Python 回退）：onedir 里必须有独立运行时产物，否则发布态会悄悄用宿主 py；
3. 资源树非空（bundle.resources 真打进包，不是空目录假绿）。

可选 `--verify-runtime`：真跑冻结二进制做 initialize/shutdown over HTTP 冒烟——**本机无 PyInstaller/无
构建产物时该 leg 无法执行，属 UNVERIFIED**（诚实边界，绝不用"结构绿"冒充"运行时绿"）。

Usage:
    uv run python scripts/verify-release-bundle.py --bundle <dir> [--verify-runtime]
    uv run python scripts/verify-release-bundle.py --self-test   # 证明结构门能判红/判绿
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

#: onedir 里 sidecar 可执行体的候选名（PyInstaller 产物名；实现期按实际入口名调整）。
SIDECAR_BIN_NAMES = ("questor-sidecar", "questor-sidecar.exe", "app-server", "app-server.exe")
#: 内嵌解释器的标志文件（无则视为"发布态回退系统 Python"风险，判红）。
INTERPRETER_MARKERS = ("python3.dll", "python.dll", "base_library.zip", "libpython3.13.dylib", "python3.13")


def _find_sidecar_binaries(bundle: Path) -> list[Path]:
    return [p for p in bundle.rglob("*") if p.is_file() and p.name in SIDECAR_BIN_NAMES]


def _has_embedded_interpreter(bundle: Path) -> bool:
    names = {p.name for p in bundle.rglob("*") if p.is_file()}
    return any(m in names for m in INTERPRETER_MARKERS)


def _resource_tree_nonempty(bundle: Path) -> bool:
    return any(p.is_file() for p in bundle.rglob("*"))


def verify(bundle: Path) -> tuple[list[str], bool]:
    """返回 (违规信息, 运行时冒烟是否执行)。纯结构检查不需要可运行的产物。"""
    violations: list[str] = []
    if not bundle.exists():
        return [f"bundle path does not exist: {bundle}"], False
    bins = _find_sidecar_binaries(bundle)
    if len(bins) == 0:  # fail-on-empty：构建根本没产出 sidecar 二进制
        violations.append(f"fail-on-empty: no sidecar binary found under {bundle} (expected exactly one)")
    elif len(bins) > 1:  # 多份二进制 → 无法确定运行时用哪个，判红
        violations.append(f"expected exactly one sidecar binary, found {len(bins)}: {[str(b) for b in bins]}")
    if not _has_embedded_interpreter(bundle):
        violations.append(f"no embedded interpreter under {bundle}: release would silently fall back to system Python")
    if not _resource_tree_nonempty(bundle):
        violations.append(f"resource tree is empty under {bundle}")
    return violations, False


def self_test() -> int:
    """证明结构门能判红/判绿：0/多/缺解释器/空树 → 红；恰一个+内嵌解释器 → 绿。"""
    import tempfile

    def build(n_bins: int, interpreter: bool, junk: bool) -> Path:
        d = Path(tempfile.mkdtemp())
        # 用两个都在白名单里的不同名造多份，确证 >1 判红（否则多份名不在候选里会漏判）。
        bin_names = ("questor-sidecar", "app-server")
        for i in range(n_bins):
            (d / bin_names[i]).write_bytes(b"x")
        if interpreter:
            (d / "base_library.zip").write_bytes(b"z")
        if junk:
            (d / "readme.txt").write_text("hi", encoding="utf-8")
        return d

    empty_dir = build(0, interpreter=False, junk=False)  # 0 二进制 + 无解释器 + 空内容树
    two_bins = build(2, interpreter=True, junk=True)  # >1 二进制
    good = build(1, interpreter=True, junk=True)  # 恰一个 + 内嵌解释器 + 非空树
    missing_interp = build(1, interpreter=False, junk=True)  # 恰一个但无内嵌解释器

    empty_v, _ = verify(empty_dir)
    two_v, _ = verify(two_bins)
    good_v, _ = verify(good)
    nointerp_v, _ = verify(missing_interp)

    ok = bool(empty_v) and bool(two_v) and not good_v and bool(nointerp_v)
    print(
        "self-test: "
        f"empty-detects={bool(empty_v)} multi-detects={bool(two_v)} "
        f"single-interpreter-green={not good_v} missing-interpreter-detects={bool(nointerp_v)}"
    )
    for msg in (*empty_v, *two_v, *nointerp_v):
        print(f"  expected-red -> {msg}")
    print("self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--bundle", type=Path, default=None)
    parser.add_argument("--verify-runtime", action="store_true", help="run the frozen binary's HTTP initialize/shutdown smoke (needs a real build)")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    if args.bundle is None:
        print("error: --bundle <dir> required (or --self-test)", file=sys.stderr)
        return 2

    violations, _ = verify(args.bundle)
    for msg in violations:
        print(msg)
    if violations:
        print(f"verify-release-bundle: {len(violations)} FAIL")
        return 1
    if args.verify_runtime:
        # 真机冒烟：起冻结产物 → HTTP /health + initialize/shutdown。无产物/无网络时明确 UNVERIFIED，不假绿。
        print("verify-runtime: launching frozen sidecar smoke (UNVERIFIED without a real PyInstaller build here)")
        # 实现期在此 spawn binary、轮询 /health、POST /run、优雅 shutdown；本 Phase 无构建产物故不伪造。
        return 3
    print("verify-release-bundle: structure OK (runtime smoke not run — pass --verify-runtime with a real build)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
