"""L2 恢复 —— 从最近 checkpoint 重建 Run（A1；ADR-0005/0014/0016）。

恢复 = 加载最近一个 turn 边界的快照，还原权威 ``Domain_State``，并对**审批生命周期**做一件
必须显式处理的事：pending 的 ApprovalRequest 若已过期，恢复时用 ``ExpireApproval`` 经 reduce
闭合（而不是让状态静默蒸发或复活）。P2 的验收点是"权限/审批状态不会在 checkpoint 悄悄丢失"，
通用的 durable resume/after_seq 加固留给 P3。
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime

from questor.contracts.events import ExpireApproval
from questor.contracts.ports import StorePort
from questor.contracts.state_schema import ApprovalStatus
from questor.state.domain_state import Run
from questor.state.reduce import reduce
from questor.state.snapshot import from_snapshot


class NoIntactCheckpointError(RuntimeError):
    """某 run 有快照但无一可完好重建（blob 损坏 / 版本不可解）：fail-closed，绝不半重建或静默当未知 run。"""


def _expire_due_approvals(run: Run, *, now: datetime) -> Run:
    """把恢复出来仍 pending 但已过期的审批，经 reduce 走 ExpireApproval 闭合（不静默丢弃）。"""
    due = [a for a in run.permission_ctx.approvals if a.status is ApprovalStatus.PENDING and a.expires_at <= now]
    for approval in due:
        # ExpireApproval 只翻转仍 open 的 tool_call；重复调用幂等。
        run, _events = reduce(run, ExpireApproval(run_id=run.run_id, request_id=approval.request_id))
    return run


async def rebuild_run(store: StorePort, run_id: str, *, now: datetime | None = None) -> Run | None:
    """从持久态重建权威 Run（ADR-0020/0021）：

    1. 取最近完好快照 → ``from_snapshot`` 得全量权威状态（含未闭合 tool_use / awaiting 审批）。
    2. 把 ``seq`` 对齐到 ``sequence_head``（快照可能落后于崩溃前已 append 的耐久事件），使续跑
       取号不复用旧 seq（ADR-0011/0020）。
    3. 仍 pending 但已过期的审批经 ``ExpireApproval`` 显式闭合（不静默蒸发/复活）。

    未闭合 tool_use 的补齐/re-dispatch 是驱动职责，留交 ``resume_and_drive``→loop 的
    ``_resume_settle_open_calls``（保证进入 provider 前配对完整）。**无任何 checkpoint 返回 ``None``**
    （未知/未落库的 run）；**有 checkpoint 但全部损坏 → 抛 ``NoIntactCheckpointError``（fail-closed）**。
    权威状态只从快照重建，不回灌输出事件（C5）。
    """
    candidates = await store.checkpoints(run_id)
    if not candidates:
        return None
    run: Run | None = None
    last_error: Exception | None = None
    for cp in candidates:  # 新→旧：逐一尝试，跳过损坏/不可解的快照
        try:
            run = from_snapshot(json.loads(cp["state_digest"]))
            break
        except Exception as exc:  # noqa: BLE001 - 快照损坏/版本不可解都往下一个回退，不半重建
            last_error = exc
    if run is None:
        raise NoIntactCheckpointError(f"run {run_id} has {len(candidates)} checkpoint(s) but none is intact: {last_error}")
    head = await store.sequence_head(run_id)
    if head > run.seq:
        run = replace(run, seq=head)
    reference = now or datetime.now(run.created_at.tzinfo)
    return _expire_due_approvals(run, now=reference)


async def resume_run(store: StorePort, run_id: str, *, now: datetime | None = None) -> Run | None:
    """向后兼容入口：等价于 ``rebuild_run``（恢复该 run 最近权威状态并闭合过期审批）。"""
    return await rebuild_run(store, run_id, now=now)
