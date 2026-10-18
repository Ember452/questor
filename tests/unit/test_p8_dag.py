"""P8 T4 判据：任务树 DAG 校验（无环/无悬空/无自环/唯一），对齐 [ADR-0037](docs/adr/0037) / I1。

校验是纯函数、在 reduce 内强制（不改状态、只返回问题清单）。先红后绿。
"""

from __future__ import annotations

from questor.contracts.state_schema import TaskKind, TaskNode
from questor.state.reduce import validate_task_tree


def _node(nid: str, *, deps: tuple[str, ...] = (), kind: TaskKind = TaskKind.TASK) -> TaskNode:
    return TaskNode(id=nid, title=nid, kind=kind, deps=deps)


def test_valid_forest_has_no_problems():
    nodes = (_node("a"), _node("b", deps=("a",)))
    assert validate_task_tree(nodes) == []


def test_empty_is_valid():
    assert validate_task_tree(()) == []


def test_self_edge_rejected():
    problems = validate_task_tree((_node("a", deps=("a",)),))
    assert any("a" in p and "itself" in p.lower() for p in problems)


def test_dangling_dep_rejected():
    problems = validate_task_tree((_node("a", deps=("ghost",)),))
    assert any("ghost" in p for p in problems)


def test_cycle_rejected():
    nodes = (_node("a", deps=("b",)), _node("b", deps=("a",)))
    problems = validate_task_tree(nodes)
    assert any("cycle" in p.lower() for p in problems)


def test_longer_cycle_rejected():
    nodes = (_node("a", deps=("c",)), _node("b", deps=("a",)), _node("c", deps=("b",)))
    problems = validate_task_tree(nodes)
    assert any("cycle" in p.lower() for p in problems)


def test_duplicate_node_id_rejected():
    nodes = (_node("a"), _node("a"))
    problems = validate_task_tree(nodes)
    assert any("duplicate" in p.lower() and "a" in p for p in problems)


def test_fan_in_multiple_deps_acyclic_is_valid():
    # 汇聚：c 依赖 a、b；a、b 各自依赖根 —— 合法 DAG（读侧就绪判定用，不代表内核主动调度）。
    nodes = (_node("root"), _node("a", deps=("root",)), _node("b", deps=("root",)), _node("c", deps=("a", "b")))
    assert validate_task_tree(nodes) == []
