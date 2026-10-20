#!/usr/bin/env python3
"""Replay-determinism invariant guard (ADR-0005/0020/0021; HARD C2/C5/C7/I4).

这是 P3 续跑正确性的**地基证明**：对同一条 Command 序列，
"连续 reduce 到底" 与 "在某个 split 处落 checkpoint、from_snapshot 重建、再继续 reduce 尾部"
必须得到**一致的权威状态**（seq/turn/status、tool_ledger、context 的 tool_use↔tool_result 配对、
permission approvals/decisions）。这正是 ROADMAP "重启能续跑/回放" 所依赖的性质，也守住
"恢复=最近快照+重放其后事件" 不因快照有损而漂移。

它比较的是权威**骨架**（忽略 new_id 生成的 message id 与 utc_now 时间戳这类非确定字段，
只比 role/block 形状、tool_call_id、审批 request_id、status、seq）——因此对随机 id/时钟免疫，
只对真正的状态漂移敏感。

- ``check``：跑全部 fixture，任一 (full != snapshot+tail) 即判红。
- ``--self-test``：既证绿（健康 fixture 通过），又证红（截断尾部/破坏配对必须被抓到）（C15）。
- **fail-on-empty**：没有任何 fixture 视为配置错误（exit 2），不是通过。

Usage:
    uv run python scripts/check_replay_determinism.py
    uv run python scripts/check_replay_determinism.py --self-test
"""

from __future__ import annotations

import argparse
import copy
import sys
import types
import typing
from collections.abc import Callable, Mapping
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from enum import Enum

from questor.contracts.events import (
    AdvanceTurn,
    AppendAssistantMessage,
    Cancel,
    Command,
    CompactContext,
    FinalizeRun,
    MarkToolValidated,
    RecordToolResult,
    ReportChildTerminal,
    RequestApproval,
    ResolveApproval,
    SpawnSubagent,
    SubmitMessage,
    UpdateTaskTree,
)
from questor.contracts.memory import RecoveryPointer
from questor.contracts.state_schema import Budget, CancelReason, ContentBlock, Message, Role, TaskKind, TaskNode, ToolArgsStatus
from questor.state.domain_state import Run
from questor.state.reduce import reduce
from questor.state.snapshot import from_snapshot, to_snapshot

_FUTURE = datetime(2099, 1, 1, tzinfo=UTC)


def _user() -> Message:
    return Message(id="u0", role=Role.USER, seq=0, content=(ContentBlock(type="text", text="go"),))


def _assistant_text(text: str, seq: int) -> Message:
    return Message(id=f"at{seq}", role=Role.ASSISTANT, seq=seq, content=(ContentBlock(type="text", text=text),))


def _assistant_tool_use(tc: str, turn: int) -> Message:
    return Message(
        id=f"a{turn}",
        role=Role.ASSISTANT,
        seq=turn,
        content=(ContentBlock(type="tool_use", tool_use_id=tc, name="read", input={"file_path": "x"}, args_status=ToolArgsStatus.VALID, raw_input="{}"),),
    )


def _fixture_approve() -> tuple[Run, list[Command], int]:
    rid = "r_ok"
    run = Run(run_id=rid, budget=Budget(max_turns=3))
    cmds: list[Command] = [
        SubmitMessage(run_id=rid, content=_user()),
        AdvanceTurn(run_id=rid, turn=1),
        AppendAssistantMessage(run_id=rid, turn=1, message=_assistant_tool_use("tc1", 1)),
        MarkToolValidated(run_id=rid, tool_call_id="tc1"),
        RequestApproval(run_id=rid, tool_call_id="tc1", request_id="req1", args_summary="read x", risk="low", reason="ask", expires_at=_FUTURE),
        ResolveApproval(run_id=rid, request_id="req1", decision="allow", decided_by="user"),
        RecordToolResult(run_id=rid, tool_call_id="tc1", status="success", result="ok"),
        FinalizeRun(run_id=rid, status="completed", exit_reason="answered"),
    ]
    return run, cmds, 5  # split 恰在审批挂起处（含未闭合 tool_use）


def _fixture_cancel_backfill() -> tuple[Run, list[Command], int]:
    rid = "r_cancel"
    run = Run(run_id=rid, budget=Budget(max_turns=3))
    cmds: list[Command] = [
        SubmitMessage(run_id=rid, content=_user()),
        AdvanceTurn(run_id=rid, turn=1),
        AppendAssistantMessage(run_id=rid, turn=1, message=_assistant_tool_use("tc9", 1)),
        MarkToolValidated(run_id=rid, tool_call_id="tc9"),
        Cancel(run_id=rid, reason=CancelReason.USER),  # 必须回填未闭合 tool_use（C7）
    ]
    return run, cmds, 3  # split 在 open 调用尚存处


def _fixture_multi_turn() -> tuple[Run, list[Command], int]:
    rid = "r_multi"
    run = Run(run_id=rid, budget=Budget(max_turns=5))
    cmds: list[Command] = [
        SubmitMessage(run_id=rid, content=_user()),
        AdvanceTurn(run_id=rid, turn=1),
        AppendAssistantMessage(run_id=rid, turn=1, message=_assistant_tool_use("tcA", 1)),
        MarkToolValidated(run_id=rid, tool_call_id="tcA"),
        RecordToolResult(run_id=rid, tool_call_id="tcA", status="success", result="done"),
        AdvanceTurn(run_id=rid, turn=2),
        FinalizeRun(run_id=rid, status="completed", exit_reason="answered"),
    ]
    return run, cmds, 5  # split 在 turn1 工具闭合、turn2 未起处


def _fixture_spawn_report() -> tuple[Run, list[Command], int]:
    """P8：父 update-tree→spawn→report 全走 reduce；验证 task_tree（含 assigned_run_id）跨快照 round-trip 确定。"""
    rid = "r_spawn"
    run = Run(run_id=rid, budget=Budget(max_turns=3))
    sub_node = TaskNode(id="n1", title="child task", kind=TaskKind.SUBAGENT)
    cmds: list[Command] = [
        SubmitMessage(run_id=rid, content=_user()),
        AdvanceTurn(run_id=rid, turn=1),
        UpdateTaskTree(run_id=rid, upsert=(sub_node,)),
        SpawnSubagent(run_id=rid, node_id="n1", child_run_id="r-child-1", spawn_key="spawn:n1:1"),
        ReportChildTerminal(run_id=rid, child_run_id="r-child-1", node_id="n1", terminal_status="completed"),
        FinalizeRun(run_id=rid, status="completed", exit_reason="answered"),
    ]
    return run, cmds, 4  # split 恰在 spawn 之后、report 之前（task_tree 含 active+assigned_run_id）


def _fixture_multi_child_report() -> tuple[Run, list[Command], int]:
    """P8：父 spawn 两子、分别 report（一个 done 一个 failed）；验证多子 task_tree 跨快照 round-trip 确定。"""
    rid = "r_multi_child"
    run = Run(run_id=rid, budget=Budget(max_turns=3))
    nodes = (TaskNode(id="c1", title="c1", kind=TaskKind.SUBAGENT), TaskNode(id="c2", title="c2", kind=TaskKind.SUBAGENT))
    cmds: list[Command] = [
        SubmitMessage(run_id=rid, content=_user()),
        UpdateTaskTree(run_id=rid, upsert=nodes),
        SpawnSubagent(run_id=rid, node_id="c1", child_run_id="rc1", spawn_key="s:c1"),
        SpawnSubagent(run_id=rid, node_id="c2", child_run_id="rc2", spawn_key="s:c2"),
        ReportChildTerminal(run_id=rid, child_run_id="rc1", node_id="c1", terminal_status="completed"),
        ReportChildTerminal(run_id=rid, child_run_id="rc2", node_id="c2", terminal_status="failed"),
        FinalizeRun(run_id=rid, status="completed", exit_reason="answered"),
    ]
    return run, cmds, 5  # split 在第一子 report 后、第二子 report 前（task_tree 半更新态）


def _fixture_compaction() -> tuple[Run, list[Command], int]:
    """P10/ADR-0048：连续两条文本消息后在内核安全点压缩。

    `CompactContext` 携带 summary/covered_hash/floor（loop 侧算好），reduce 纯应用；
    split 恰在压缩命令**之前**，使 CompactContext 进尾部重放——验证从快照重放该命令与
    连续 reduce 得到一致的压缩后骨架（含 summary/recovery_pointers）。"""
    rid = "r_compact"
    run = Run(run_id=rid, budget=Budget(max_turns=3))
    cmds: list[Command] = [
        SubmitMessage(run_id=rid, content=_user()),
        AdvanceTurn(run_id=rid, turn=1),
        AppendAssistantMessage(run_id=rid, turn=1, message=_assistant_text("a1", 1)),
        CompactContext(
            run_id=rid,
            evict_start=1,
            evict_end=2,
            summary_text="[compacted a1]",
            new_floor=2,
            new_pointers=(RecoveryPointer(seq_from=1, seq_to=1, covered_hash="sha256:abc"),),
        ),
        FinalizeRun(run_id=rid, status="completed", exit_reason="answered"),
    ]
    return run, cmds, 3  # split 在压缩命令之前（pre_compact 快照位置）


def _fixture_compaction_after_split() -> tuple[Run, list[Command], int]:
    """P10/Major-2 盲区补（审计 F2）：split 落在 CompactContext **之后**。

    这样快照捕获的是**压缩后**态（含 summary/compaction_floor/recovery_pointers），尾只重放
    FinalizeRun——若快照序列化丢弃压缩态，from_snapshot 重建就丢锈而连续 reduce 不丢 → 判红。
    与 _fixture_compaction（split 在压缩前）互补，共同钉住"压缩态经快照 round-trip 确定"。"""
    run, cmds, _ = _fixture_compaction()
    return run, cmds, 4  # split 在 CompactContext 之后、FinalizeRun 之前


FIXTURES: list[tuple[str, Callable[[], tuple[Run, list[Command], int]]]] = [
    ("approve", _fixture_approve),
    ("cancel-backfill", _fixture_cancel_backfill),
    ("multi-turn", _fixture_multi_turn),
    ("spawn-report", _fixture_spawn_report),
    ("multi-child-report", _fixture_multi_child_report),
    ("compaction", _fixture_compaction),
    ("compaction-after-split", _fixture_compaction_after_split),
]


def _replay_full(run: Run, cmds: list[Command]) -> Run:
    for cmd in cmds:
        run, _ = reduce(run, cmd)
    return run


def _replay_snapshot_tail(run: Run, cmds: list[Command], split: int) -> Run:
    for cmd in cmds[:split]:
        run, _ = reduce(run, cmd)
    # 落 checkpoint → 重建权威状态（模拟进程重启后从持久态出发）。
    run = from_snapshot(to_snapshot(run))
    for cmd in cmds[split:]:
        run, _ = reduce(run, cmd)
    return run


def _unwrap_annotation(tp: object) -> tuple[object, bool]:
    """拆 ``X | None`` / ``tuple[X, ...]``：返回 (内层类型, 是否序列)。

    ``Optional[X]`` 只去 Optional、**不**标成序列（否则 ``summary: str | None`` 会被误写成
    ``Run.context.summary[]``，于是删字段自测报错路径与实际字段名不一致）。"""
    origin = typing.get_origin(tp)
    if origin in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(tp) if a is not type(None)]
        return _unwrap_annotation(args[0]) if len(args) == 1 else (tp, False)
    if origin in (tuple, list, set, frozenset):
        args = typing.get_args(tp)
        return (args[0], True) if args else (tp, True)
    return tp, False


def _schema_paths(cls: type, prefix: str, seen: set[type]) -> list[str]:
    """反射 ``Run`` 及内嵌 dataclass 的**声明字段**，产出 ``Run.context.summary`` 形式的路径。

    B0.5（OPT-1）：重放比对集不能再靠手工白名单——本函数是"每个字段都必须进比对集"的
    真值来源；新增字段而未进 ``_canonical`` 时，``_coverage_missing`` 会以字段路径判红
    （历史上 summary/covered_hash/floor 漂移曾全绿假判，见本模块 L238 注释）。"""
    out: list[str] = []
    hints = typing.get_type_hints(cls)
    for f in fields(cls):
        inner, is_seq = _unwrap_annotation(hints.get(f.name, f.type))
        out.append(f"{prefix}.{f.name}" + ("[]" if is_seq else ""))
        if is_dataclass(inner) and inner not in seen:
            seen.add(inner)  # type: ignore[arg-type]
            # 序列内的 dataclass：前缀带 ``[]``，使路径与 ``_has_path`` 的下钻语义一致。
            child_prefix = f"{prefix}.{f.name}[]" if is_seq else f"{prefix}.{f.name}"
            out.extend(_schema_paths(inner, child_prefix, seen))  # type: ignore[arg-type]
    return out


def _leaf(value: object) -> object:
    """把叶子值归一成**可跨两次重放比较**的形状。

    时间戳是墙上时钟：两次重放各取一次 ``utc_now``，值必然不同——故只保留"有/无"的
    存在性（``"<ts>"``），不比较具体值；集合/mapping 排序后比较，消除哈希序噪声。"""
    if isinstance(value, datetime):
        return "<ts>"
    if isinstance(value, Enum):
        return f"{type(value).__name__}.{value.value}"
    if isinstance(value, Mapping):
        return tuple(sorted((str(k), repr(v)) for k, v in value.items()))
    if isinstance(value, (set, frozenset)):
        return tuple(sorted(repr(v) for v in value))
    if isinstance(value, (tuple, list)):
        return tuple(_leaf(v) for v in value)
    return value


def _project_value(tp: object, value: object, path: str) -> object:
    """按**声明类型**（而非仅实例）投影：空 tuple 也保留字段形状，覆盖率检查才不会误判。"""
    if value is None:
        return None
    inner, is_seq = _unwrap_annotation(tp)
    if is_dataclass(inner) and is_dataclass(value):
        return _project(inner, value, path)  # type: ignore[arg-type]
    if is_seq and isinstance(value, (tuple, list, set, frozenset)):
        return tuple(_project_value(inner, item, path) for item in value)
    return _leaf(value)


def _project(cls: type, value: object, path: str) -> dict:
    """把一个 dataclass 实例投影成 ``{字段名: 归一值}``（字段名逐字取 ``dataclasses.fields``）。"""
    hints = typing.get_type_hints(cls)
    return {
        f.name: _project_value(hints.get(f.name, f.type), getattr(value, f.name), f"{path}.{f.name}")
        for f in fields(cls)
    }


#: 反射得到的字段路径（模块加载时算一次）：新增字段自动出现在这里 = 必须进比对集。
_SCHEMA_PATHS: list[str] = _schema_paths(Run, "Run", {Run})

#: fail-on-empty 锚点：反射若静默失效（例如 ``Run`` 换实现），覆盖率检查会假绿。
_SCHEMA_ANCHORS: tuple[str, ...] = (
    "Run.run_id",
    "Run.context.items[].role",
    "Run.tool_ledger.calls[].status",
    "Run.permission_ctx.approvals[].status",
    "Run.task_tree.nodes[].deps[]",
)


def _has_path(projection: object, path: str) -> bool:
    """按 ``Run.context.summary`` / ``Run.context.items[].role`` 逐段查投影键。

    空集合视为"形状已覆盖"（深层键在无元素时无从比对；fixture 一旦填充即由正常比对捕获）。"""
    node = projection
    for part in path.split("."):
        is_seq = part.endswith("[]")
        name = part[:-2] if is_seq else part
        if not isinstance(node, dict) or name not in node:
            return False
        node = node[name]
        if node is None:
            return True  # 可选子对象为 None："有/无"已由父字段比较，深层键无从存在
        if is_seq:
            if node is None or not isinstance(node, tuple):
                return True
            if not node:
                return True
            node = node[0]
    return True


def _coverage_missing(canonical: dict) -> list[str]:
    """比对集覆盖率：每个反射字段路径必须在 ``_canonical`` 的 ``schema`` 投影里出现。"""
    schema = canonical.get("schema")
    if not isinstance(schema, dict):
        return ["Run (schema projection missing from _canonical)"]
    return [path for path in _SCHEMA_PATHS if not _has_path(schema, path)]


def _canonical(run: Run) -> dict:
    """权威骨架：忽略随机 message id / 时间戳，只对状态漂移敏感。

    ``schema`` 键（B0.5）是**全字段**投影：上面手工条目仍在（既有断言不变），但它只覆盖
    手工挑出的骨架；漏字段的缺口由反射投影补上，缺一个字段即由 :func:`_coverage_missing` 判红。"""
    items = tuple(
        (m.role.value, tuple(b.type for b in m.content), tuple(b.tool_use_id or "" for b in m.content), tuple((b.text or "") for b in m.content))
        for m in run.context.items
    )
    calls = tuple(sorted((c.tool_call_id, c.name, c.status.value) for c in run.tool_ledger.calls))
    approvals = tuple(sorted((a.request_id, a.tool_call_id, a.status.value, a.decision or "") for a in run.permission_ctx.approvals))
    # P8：task_tree 必须进权威骨架——否则 DAG/spawn 状态漂移全绿（最危险的静默错，ADR-0037/0038）。
    task_tree = tuple(
        sorted(
            (n.id, n.status.value, n.kind.value, n.parent_id or "", tuple(n.deps), n.assigned_run_id or "")
            for n in run.task_tree.nodes
        )
    )
    return {
        "status": run.status.value,
        "turn": run.turn,
        "seq": run.seq,
        "cancel": run.cancel_reason.value if run.cancel_reason else None,
        "mode": run.permission_ctx.mode,
        "n_decisions": len(run.permission_ctx.decisions),
        "errors": len(run.error_stack),
        "items": items,
        "calls": calls,
        "approvals": approvals,
        "task_tree": task_tree,
        # P10/ADR-0048：压缩态必进权威骨架——否则 summary/covered_hash/floor 漂移会全绿假判（最危险的静默错）。
        "summary": run.context.summary,
        "compaction_floor": run.context.compaction_floor,
        "recovery_pointers": tuple((p.seq_from, p.seq_to, p.covered_hash) for p in run.context.recovery_pointers),
        # B0.5（OPT-1）：Run 及内嵌 dataclass 的全字段反射投影。新增字段若不在投影里 = 缺字段判红。
        "schema": {"Run": _project(Run, run, "Run")},
    }


def _check_one(name: str, factory: Callable[[], tuple[Run, list[Command], int]]) -> list[str]:
    run, cmds, split = factory()
    full = _canonical(_replay_full(run, cmds))
    tail = _canonical(_replay_snapshot_tail(run, cmds, split))
    problems: list[str] = []
    if full != tail:
        diff_keys = sorted(k for k in full if full[k] != tail[k])
        problems.append(f"{name}: snapshot+tail diverges from continuous replay in {diff_keys}")
    # B0.5：比对集本身必须覆盖 Run 的每个字段（否则"全绿"只是没比到）。
    missing = _coverage_missing(full)
    if missing:
        problems.append(f"{name}: _canonical misses reflected field(s): {', '.join(missing)}")
    return problems


def check() -> int:
    if not FIXTURES:
        print("no fixtures defined (fail-on-empty)", file=sys.stderr)
        return 2
    problems = [p for name, factory in FIXTURES for p in _check_one(name, factory)]
    for msg in problems:
        print(msg, file=sys.stderr)
    if problems:
        return 1
    print(f"replay determinism OK: {len(FIXTURES)} fixtures — snapshot+tail == continuous reduce")
    return 0


def _self_test_green() -> bool:
    return not any(_check_one(name, factory) for name, factory in FIXTURES)


def _self_test_red() -> bool:
    """破坏样例：只落快照、丢掉尾部再比较，权威 seq/状态必然落后 → 守卫必须判红。"""
    run, cmds, split = _fixture_approve()
    snap_only = from_snapshot(to_snapshot(_replay_full(run, cmds[:split])))
    return _canonical(snap_only) != _canonical(_replay_full(run, cmds))


def _self_test_field_coverage() -> tuple[bool, str]:
    """B0.5 判红证明：从 ``_canonical`` 删一个字段 → 覆盖率必须报出该字段路径；恢复 → 绿。"""
    healthy = not _coverage_missing(_canonical(Run(run_id="r_cov")))
    broken = copy.deepcopy(_canonical(Run(run_id="r_cov")))
    del broken["schema"]["Run"]["context"]["summary"]
    caught_paths = _coverage_missing(broken)
    caught = "Run.context.summary" in caught_paths
    restored = copy.deepcopy(broken)
    restored["schema"]["Run"]["context"]["summary"] = None
    green_again = not _coverage_missing(restored)
    detail = (
        f"healthy-green={healthy} deleted-field→red={caught} (hit={caught_paths[:1]}) "
        f"restored→green={green_again} fields={len(_SCHEMA_PATHS)}"
    )
    return healthy and caught and green_again, detail


def _self_test_anchors() -> bool:
    """fail-on-empty：反射必须真的枚举出字段，且锚点路径都在（否则覆盖率检查假绿）。"""
    return bool(_SCHEMA_PATHS) and all(anchor in _SCHEMA_PATHS for anchor in _SCHEMA_ANCHORS)


def self_test() -> int:
    green = _self_test_green()
    red = _self_test_red()
    coverage_ok, coverage_detail = _self_test_field_coverage()
    anchors_ok = _self_test_anchors()
    ok = green and red and coverage_ok and anchors_ok
    print(f"self-test: healthy-green={green} truncated-caught={red} schema-anchors={anchors_ok}")
    print(f"self-test: {coverage_detail}")
    print("self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    return self_test() if args.self_test else check()


if __name__ == "__main__":
    raise SystemExit(main())
