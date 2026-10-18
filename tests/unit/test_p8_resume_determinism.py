"""P8 DoD⑦ 可证伪判据：多子 run 交织顺序不影响父回放结果（reduce 级确定性）。

子终态回父只经 `ReportChildTerminal` Command；每个 report 只动自己那一个节点，故父最终权威态
（task_tree 各节点状态 + 总 seq）与子报告到达顺序无关。这是"续跑多 run 交织后正确"的骨架证明
（进程/机级交织属 P9/C12，UNVERIFIED）。
"""

from __future__ import annotations

from questor.contracts.events import ReportChildTerminal, SpawnSubagent, UpdateTaskTree
from questor.contracts.state_schema import TaskKind, TaskNode
from questor.state.domain_state import Run
from questor.state.reduce import reduce


def _parent_with_two_children() -> Run:
    run = Run(run_id="rp")
    nodes = (
        TaskNode(id="a", title="a", kind=TaskKind.SUBAGENT),
        TaskNode(id="b", title="b", kind=TaskKind.SUBAGENT),
    )
    run, _ = reduce(run, UpdateTaskTree(run_id="rp", upsert=nodes))
    run, _ = reduce(run, SpawnSubagent(run_id="rp", node_id="a", child_run_id="ra", spawn_key="s:a"))
    run, _ = reduce(run, SpawnSubagent(run_id="rp", node_id="b", child_run_id="rb", spawn_key="s:b"))
    return run


def _replay(report_order: list[tuple[str, str]]) -> Run:
    run = _parent_with_two_children()
    for node_id, child_run_id in report_order:
        run, _ = reduce(
            run,
            ReportChildTerminal(run_id="rp", child_run_id=child_run_id, node_id=node_id, terminal_status="completed"),
        )
    return run


def test_child_report_order_does_not_affect_parent_authoritative_state():
    ab = _replay([("a", "ra"), ("b", "rb")])
    ba = _replay([("b", "rb"), ("a", "ra")])
    # 节点状态（权威 task_tree）一致：两节点均 DONE。
    assert {n.id: n.status.value for n in ab.task_tree.nodes} == {n.id: n.status.value for n in ba.task_tree.nodes}
    assert all(n.status.value == "done" for n in ab.task_tree.nodes)
    # 总 seq 一致（两条 report 各占 2 seq，与顺序无关）。
    assert ab.seq == ba.seq
