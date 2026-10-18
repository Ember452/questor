"""P8 T9（可验证部分）：spawn/report 后的 task_tree 必须能经快照完整 round-trip（resume 前置）。

对齐 ADR-0020/0021/0024：恢复永远从持久态出发。子 agent 的权威关联（kind/assigned_run_id/status）
若不能 round-trip，`--resume` 就会丢编排态。**跨进程 re-link（重驱孤儿子的自动回连）继承
ADR-0021/0038 的"claim/delivery_state 账本后置 P9"边界**——本测试只钉死"持久化不丢、幂等不重"这条不变式。
"""

from __future__ import annotations

from questor.contracts.events import ReportChildTerminal, SpawnSubagent, UpdateTaskTree
from questor.contracts.state_schema import TaskKind, TaskNode, TaskStatus
from questor.state.domain_state import Run
from questor.state.reduce import reduce
from questor.state.snapshot import from_snapshot, to_snapshot


def _spawned_parent() -> Run:
    run = Run(run_id="rp")
    run, _ = reduce(run, UpdateTaskTree(run_id="rp", upsert=(TaskNode(id="n1", title="t", objective="child task", kind=TaskKind.SUBAGENT),)))
    run, _ = reduce(run, SpawnSubagent(run_id="rp", node_id="n1", child_run_id="rc", spawn_key="s1"))
    run, _ = reduce(run, ReportChildTerminal(run_id="rp", child_run_id="rc", node_id="n1", terminal_status="completed", result_ref="artifact://x"))
    return run


def test_snapshot_roundtrip_preserves_subagent_task_tree() -> None:
    run = _spawned_parent()
    restored = from_snapshot(to_snapshot(run))
    node = next(n for n in restored.task_tree.nodes if n.id == "n1")
    assert node.kind is TaskKind.SUBAGENT
    assert node.assigned_run_id == "rc"  # 子 run 关联不丢
    assert node.status is TaskStatus.DONE  # 回填终态不丢
    assert restored.seq == run.seq and restored.status is run.status


def test_replay_after_snapshot_is_idempotent_for_spawn_report() -> None:
    # 快照点后再重放同 Spawn/Report（崩溃重投）：reduce 幂等 → 不产生第二个子、不重复回填。
    run = _spawned_parent()
    restored = from_snapshot(to_snapshot(run))
    again, events = reduce(restored, SpawnSubagent(run_id="rp", node_id="n1", child_run_id="rc", spawn_key="s1"))
    assert again is restored  # 同 child 已绑 → no-op
    assert not any(e.type == "peer_started" for e in events)
    again2, events2 = reduce(restored, ReportChildTerminal(run_id="rp", child_run_id="rc", node_id="n1", terminal_status="completed"))
    assert not any(e.type == "peer_ended" for e in events2)  # 节点已终态 → 不重复回灌
