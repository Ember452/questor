"""DoD③ 静态收口测试（审计 §6-4：补 plan 命名的 test_p4_memory_single_writer.py）。

加载 ``scripts/check_layering_ast.py`` 守卫，断言：``capabilities``/``policy``/``surfaces`` 任一层 import
具体 ``store_memory_sqlite`` 都判红（记忆写/读唯一入口 = Command→reduce / ctx 受控方法，策略无裸句柄，C4/C16）；
外→内的合法方向（providers→memory）不误伤。动态侧（reduce 唯一写、记忆正文不进 Domain_State）由
``test_reduce_memory.py`` / ``test_p4_memory_dod.py`` 覆盖。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("check_layering_ast", _ROOT / "scripts" / "check_layering_ast.py")
assert _spec is not None and _spec.loader is not None
_ast = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ast)

_CONCRETE_STORE = "from questor.providers.store_memory_sqlite import SQLiteMemoryStore\n"


def test_guard_flags_concrete_memory_store_import_in_each_outer_layer() -> None:
    for layer in ("capabilities", "policy", "surfaces"):
        violations = _ast.analyze_source(_CONCRETE_STORE, layer)
        assert any("store_memory_sqlite" in v for v in violations), f"{layer} importing concrete store must go red"


def test_guard_allows_inner_import_direction() -> None:
    # providers(L5) → memory(L1) 是外→内合法，不应误判。
    assert _ast.analyze_source("from questor.memory.search import fuse\n", "providers") == []


def test_real_source_tree_has_no_memory_layering_violations() -> None:
    violations, scanned = _ast.check(_ROOT / "src" / "questor")
    assert scanned > 0  # fail-on-empty：真扫到文件
    assert not [v for v in violations if "store_memory_sqlite" in v or "'memory'" in v]
