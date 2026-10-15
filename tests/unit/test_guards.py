"""P0 DoD —— 机械守卫可信（能判红；扫描真实）。

加载 ``scripts/`` 守卫模块，断言其 ``--self-test`` 样板能检出违规（而非假绿），
且当前仓能通过（C15：fail-on-empty + self-test）。
"""

from __future__ import annotations

import importlib.util
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ast_layering_guard_self_test() -> None:
    ast_guard = _load("check_layering_ast", "check_layering_ast.py")
    assert ast_guard.self_test() == 0  # flags a bad dynamic import, passes a good one


def test_ast_scan_current_tree_clean_and_nonempty() -> None:
    ast_guard = _load("check_layering_ast", "check_layering_ast.py")
    violations, scanned = ast_guard.check(REPO_ROOT / "src" / "questor")
    assert scanned > 0, "fail-on-empty: guard scanned nothing"
    assert violations == []


def test_ast_flags_concrete_violation() -> None:
    ast_guard = _load("check_layering_ast", "check_layering_ast.py")
    bad = "import questor.surfaces.cli\n"  # contracts must not import L6
    assert ast_guard.analyze_source(bad, "contracts")


def test_protocol_schema_sync() -> None:
    proto = _load("check_protocol_schema", "check_protocol_schema.py")
    assert proto.self_test() == 0
    assert proto.check() == 0


def test_thread_leak_guard_self_test() -> None:
    """线程泄漏守卫必须能判红（检出故意泄漏）也能判绿（释放后干净）。

    这个守卫存在的理由：忘记 close() 的 aiosqlite 连接会留下非守护工作线程，
    pytest 跑完全部测试后进程仍卡在解释器退出的 join 上 → CI 的 pytest step 永不结束。
    """
    leak_guard = _load("check_thread_leak", "check_thread_leak.py")
    assert leak_guard.self_test() == 0


def test_thread_leak_guard_detects_real_leak_and_stays_clean_on_current_suite() -> None:
    """真实泄漏必须被检出（能红）；且当前基线无非守护线程泄漏（不是假守卫）。"""
    leak_guard = _load("check_thread_leak", "check_thread_leak.py")

    before = leak_guard.snapshot()
    assert before, "fail-on-empty: no baseline threads visible"

    release = threading.Event()

    def _blocked() -> None:
        release.wait()

    thief = threading.Thread(target=_blocked, name="leak-probe")
    thief.start()
    try:
        caught = leak_guard.detect(before, grace_seconds=0.3)
        assert [t.name for t in caught] == ["leak-probe"]
        assert "leak-probe" in leak_guard.report(caught)  # 失败文案里要带线程名，否则无法定位
    finally:
        release.set()
        thief.join(timeout=2.0)
    assert leak_guard.detect(before, grace_seconds=0.0) == []
