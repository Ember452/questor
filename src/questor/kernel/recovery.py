"""L2 恢复 —— 从最近 checkpoint 重建 Run（A1；ADR-0005）。

恢复 = 加载最近一个 turn 边界的快照（loop 写下的、配对一致的重建点），还原权威
``Domain_State``。P1 每个 turn 边界都落快照，故重启后能从上一个已完成 turn 续跑；
``parallel`` 关闭，因此不存在多 pending 调用的再水合复杂度。
"""

from __future__ import annotations

import json

from questor.contracts.ports import StorePort
from questor.state.domain_state import Run
from questor.state.snapshot import from_snapshot


async def resume_run(store: StorePort, run_id: str) -> Run | None:
    """返回该 run 最近 checkpoint 时刻的 Run；无 checkpoint 则返回 ``None``。"""
    checkpoint = await store.latest_checkpoint(run_id)
    if checkpoint is None:
        return None
    return from_snapshot(json.loads(checkpoint["state_digest"]))
