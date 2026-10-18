"""P8 T3 判据：reduce 的 SpawnSubagent / ReportChildTerminal / UpdateTaskTree 分支（先红后绿）。

对齐 [ADR-0038](docs/adr/0038) / [ADR-0037](docs/adr/0037)：reduce 是唯一写者、纯状态机、不建 run；
非法 DAG 拒 + 发错误事件、不改树、不崩；跨 run 只经 Command。
"""

from __future__ import annotations

from questor.contracts.events import (
    EventType,
    ReportChildTerminal,
    SpawnSubagent,
    UpdateTaskTree,
)
from questor.contracts.state_schema import TaskKind, TaskNode, TaskStatus
from questor.state.domain_state import Run, TaskTree
from questor.state.reduce import reduce


def _run(nodes: tuple[TaskNode, ...] = ()) -> Run:
    return Run(run_id="r-parent", task_tree=TaskTree(nodes=nodes))


def _subagent_node(nid: str = "n1") -> TaskNode:
    return TaskNode(id=nid, title=nid, kind=TaskKind.SUBAGENT)


def _data(envs, etype: str):
    return [e.data for e in envs if e.type == etype]


def test_update_task_tree_valid_applies_and_emits():
    run = _run()
    cmd = UpdateTaskTree(run_id="r-parent", upsert=(_subagent_node("n1"),))
    new, events = reduce(run, cmd)
    assert [n.id for n in new.task_tree.nodes] == ["n1"]
    assert _data(events, EventType.NODE_UPDATED), "应发 node_updated"


def test_update_task_tree_cycle_rejected_tree_unchanged():
    run = _run()
    bad = (TaskNode(id="a", title="a", deps=("b",)), TaskNode(id="b", title="b", deps=("a",)))
    new, events = reduce(run, UpdateTaskTree(run_id="r-parent", upsert=bad))
    assert new.task_tree.nodes == ()  # 非法即不改树
    assert any(e.type == EventType.WARNING for e in events)  # 出声，不静默


def test_update_task_tree_dangling_rejected():
    run = _run()
    new, events = reduce(run, UpdateTaskTree(run_id="r-parent", upsert=(TaskNode(id="a", title="a", deps=("ghost",)),)))
    assert new.task_tree.nodes == ()
    assert any(e.type == EventType.WARNING for e in events)


def test_spawn_subagent_binds_and_emits_peer_started():
    run = _run((_subagent_node("n1"),))
    new, events = reduce(run, SpawnSubagent(run_id="r-parent", node_id="n1", child_run_id="r-child", spawn_key="s1"))
    node = next(n for n in new.task_tree.nodes if n.id == "n1")
    assert node.assigned_run_id == "r-child"
    assert node.status is TaskStatus.ACTIVE
    started = _data(events, EventType.PEER_STARTED)
    assert started and started[0]["child_run_id"] == "r-child" and started[0]["node_id"] == "n1"


def test_spawn_subagent_is_idempotent_same_child():
    run = _run((_subagent_node("n1"),))
    once, _ = reduce(run, SpawnSubagent(run_id="r-parent", node_id="n1", child_run_id="r-child", spawn_key="s1"))
    twice, events2 = reduce(once, SpawnSubagent(run_id="r-parent", node_id="n1", child_run_id="r-child", spawn_key="s1"))
    assert twice is once  # 同 child 再报 = no-op
    assert not _data(events2, EventType.PEER_STARTED)


def test_spawn_subagent_unknown_node_rejected():
    run = _run()
    new, events = reduce(run, SpawnSubagent(run_id="r-parent", node_id="ghost", child_run_id="r-child", spawn_key="s1"))
    assert new is run
    assert any(e.type == EventType.WARNING for e in events)


def test_report_child_terminal_sets_status_and_emits_peer_ended():
    run = _run((_subagent_node("n1"),))
    run, _ = reduce(run, SpawnSubagent(run_id="r-parent", node_id="n1", child_run_id="r-child", spawn_key="s1"))
    new, events = reduce(run, ReportChildTerminal(run_id="r-parent", child_run_id="r-child", node_id="n1", terminal_status="completed"))
    node = next(n for n in new.task_tree.nodes if n.id == "n1")
    assert node.status is TaskStatus.DONE
    ended = _data(events, EventType.PEER_ENDED)
    assert ended and ended[0]["terminal_status"] == "completed"


def test_report_child_terminal_is_idempotent():
    run = _run((_subagent_node("n1"),))
    run, _ = reduce(run, SpawnSubagent(run_id="r-parent", node_id="n1", child_run_id="r-child", spawn_key="s1"))
    run, _ = reduce(run, ReportChildTerminal(run_id="r-parent", child_run_id="r-child", node_id="n1", terminal_status="completed"))
    twice, events = reduce(run, ReportChildTerminal(run_id="r-parent", child_run_id="r-child", node_id="n1", terminal_status="failed"))
    assert not _data(events, EventType.PEER_ENDED)  # 节点已终态 → 不重复发
    node = next(n for n in twice.task_tree.nodes if n.id == "n1")
    assert node.status is TaskStatus.DONE  # 不被迟到 failed 翻案（first-writer-wins）


def test_report_child_terminal_mismatched_child_rejected():
    run = _run((_subagent_node("n1"),))
    run, _ = reduce(run, SpawnSubagent(run_id="r-parent", node_id="n1", child_run_id="r-child", spawn_key="s1"))
    new, events = reduce(run, ReportChildTerminal(run_id="r-parent", child_run_id="r-OTHER", node_id="n1", terminal_status="completed"))
    assert new is run
    assert any(e.type == EventType.WARNING for e in events)
