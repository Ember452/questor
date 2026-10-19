"""P8 T1 契约扩面的判红/判绿测试（先红后绿）：peer 事件 type + spawn/report/update Command + fan-out 预算字段。

对齐 [ADR-0042](docs/adr/0042) / [ADR-0041](docs/adr/0041) / [ADR-0038](docs/adr/0038)。
"""

from __future__ import annotations

import dataclasses

from questor.contracts.events import (
    EVENT_SCHEMA_VERSION,
    Command,
    EventType,
    ReportChildTerminal,
    SpawnSubagent,
    UpdateTaskTree,
)
from questor.contracts.state_schema import Budget, TaskNode


def test_peer_event_types_are_defined_additive():
    # 只增 type、不 bump v（ADR-0042：additive 先例 memory_written 19→20、peer 20→22）。
    assert EventType.PEER_STARTED == "peer_started"
    assert EventType.PEER_ENDED == "peer_ended"
    assert EVENT_SCHEMA_VERSION == 1


def test_peer_event_types_in_command_neutral():
    # peer_* 是 Event，不进 Command 联合（C5：Event 不反哺状态）。
    assert "peer_started" not in {getattr(c, "type", None) for c in Command.__args__}


def test_spawn_report_update_commands_exist():
    for cmd in (SpawnSubagent, ReportChildTerminal, UpdateTaskTree):
        assert cmd.type  # 带类型 Command 名
        assert cmd in Command.__args__


def test_spawn_subagent_is_frozen():
    cmd = SpawnSubagent(run_id="r-parent", node_id="n1", child_run_id="r-child", spawn_key="spawn:n1:1")
    assert dataclasses.is_dataclass(cmd)
    try:
        cmd.child_run_id = "x"  # type: ignore[misc]
        raise AssertionError("SpawnSubagent must be frozen")
    except dataclasses.FrozenInstanceError:
        pass


def test_peer_data_described_by_wire_whitelist():
    # peer_* 的载荷形状由 EXTERNAL_EVENT_FIELDS + event.schema.json 单一真源定义（#164：
    # 旧的 Python dataclass 只是重复描述、无生产构造点 → 已删）。此处钉住 wire 契约不变。
    from questor.kernel.events import EXTERNAL_EVENT_FIELDS

    assert EXTERNAL_EVENT_FIELDS[EventType.PEER_STARTED] == frozenset({"parent_run_id", "child_run_id", "node_id"})
    assert EXTERNAL_EVENT_FIELDS[EventType.PEER_ENDED] == frozenset(
        {"parent_run_id", "child_run_id", "node_id", "terminal_status", "result_ref", "resumable_hint"}
    )


def test_budget_fanout_fields_optional_and_conservative():
    b = Budget()
    assert b.max_parallel_children is None  # 默认不允许 fan-out（保守）
    assert b.max_tree_depth is None
    b2 = Budget(max_parallel_children=4, max_tree_depth=1)
    assert b2.max_parallel_children == 4 and b2.max_tree_depth == 1


def test_budget_fanout_nonpositive_rejected():
    for bad in (0, -1):
        try:
            Budget(max_parallel_children=bad)
            raise AssertionError(f"max_parallel_children={bad} must be rejected")
        except ValueError:
            pass
        try:
            Budget(max_tree_depth=bad)
            raise AssertionError(f"max_tree_depth={bad} must be rejected")
        except ValueError:
            pass


def test_tasknode_fields_unchanged_snap_stays_v3():
    # ADR-0037：TaskNode 字段不扩（无 edge_kind/path/depth/resumable），快照 schema 保持 v3。
    fields = {f.name for f in dataclasses.fields(TaskNode)}
    assert fields == {"id", "title", "objective", "parent_id", "kind", "status", "deps", "assigned_run_id", "result"}
    for forbidden in ("edge_kind", "path", "depth", "resumable"):
        assert forbidden not in fields
