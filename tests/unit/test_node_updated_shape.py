"""P7 T11：把 draft 的 `node_updated` 从"原样透传"（`EXTERNAL_EVENT_FIELDS[...] is None`）**additive 定形**。

`node_updated` 目前无生产者（任务树/DAG 属 P8），但它挂在 `None` 透传上——一旦 P8 产出富节点，透传会把
任意键原样外发，绕过白名单纪律（违 C18 有界 / C13 派生态）。T11 预先把其外部形状定为**有界白名单**：
只 `node_id/status/title/parent_id` 过门，其余（含 prompt/result 类）一律滤掉。判红点：
- 内部 `node_updated` 带越权键（如 prompt）时，`project` 后**只剩白名单键**。
- `protocol/event.schema.json` `$defs.node_updated` 收紧为对象白名单后，三处 lockstep 仍绿（见 CI 守卫）。
"""

from __future__ import annotations

from questor.contracts.events import Envelope, EventType
from questor.kernel.events import EXTERNAL_EVENT_FIELDS, project


def test_node_updated_whitelist_is_shaped_not_passthrough() -> None:
    """`None` 透传已消除：node_updated 现受白名单约束（去 draft 透传 hazards）。"""
    allowed = EXTERNAL_EVENT_FIELDS[EventType.NODE_UPDATED]
    assert allowed is not None, "node_updated 不应再原样透传（应 additive 定形为白名单）"
    assert set(allowed) == {"node_id", "status", "title", "parent_id"}, allowed


def test_project_strips_unlisted_node_updated_keys() -> None:
    """越权键（prompt 类载荷）不得外发：project 后 data 只剩白名单键。"""
    internal = Envelope(
        v=1,
        seq=1,
        run_id="run_x",
        type=EventType.NODE_UPDATED,
        data={"node_id": "n1", "status": "pending", "prompt": "机密上下文", "result": {"big": "payload"}},
    )
    projected = project(internal)
    assert projected is not None
    assert set(projected.data) == {"node_id", "status"}, projected.data  # 越权键被滤掉
