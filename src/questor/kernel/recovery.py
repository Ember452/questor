"""L2 恢复 —— 从最近 checkpoint 重建 Run（A1；ADR-0005/0014/0016）。

恢复 = 加载最近一个 turn 边界的快照，还原权威 ``Domain_State``，并对**审批生命周期**做一件
必须显式处理的事：pending 的 ApprovalRequest 若已过期，恢复时用 ``ExpireApproval`` 经 reduce
闭合（而不是让状态静默蒸发或复活）。P2 的验收点是"权限/审批状态不会在 checkpoint 悄悄丢失"，
通用的 durable resume/after_seq 加固留给 P3。
"""

from __future__ import annotations

import json
from datetime import datetime

from questor.contracts.events import ExpireApproval
from questor.contracts.ports import StorePort
from questor.contracts.state_schema import ApprovalStatus
from questor.state.domain_state import Run
from questor.state.reduce import reduce
from questor.state.snapshot import from_snapshot


def _expire_due_approvals(run: Run, *, now: datetime) -> Run:
    """把恢复出来仍 pending 但已过期的审批，经 reduce 走 ExpireApproval 闭合（不静默丢弃）。"""
    due = [a for a in run.permission_ctx.approvals if a.status is ApprovalStatus.PENDING and a.expires_at <= now]
    for approval in due:
        # ExpireApproval 只翻转仍 open 的 tool_call；重复调用幂等。
        run, _events = reduce(run, ExpireApproval(run_id=run.run_id, request_id=approval.request_id))
    return run


async def resume_run(store: StorePort, run_id: str, *, now: datetime | None = None) -> Run | None:
    """返回该 run 最近 checkpoint 时刻的 Run（已按当前时间闭合过期审批）；无 checkpoint 返回 ``None``。"""
    checkpoint = await store.latest_checkpoint(run_id)
    if checkpoint is None:
        return None
    run = from_snapshot(json.loads(checkpoint["state_digest"]))
    reference = now or datetime.now(run.created_at.tzinfo)
    resumed = _expire_due_approvals(run, now=reference)
    return resumed
