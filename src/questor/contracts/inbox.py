"""L0 Command Inbox 契约（ADR-0013；HARD C16）。

所有 surfaces（CLI/HTTP/桌面/IM）都只能把写意图提交到对应 run 的 inbox。本模块只定义
输入词汇与 receipt，不做队列、不调用 reduce——reduce 的唯一消费者仍是 L2 kernel。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from questor.contracts.events import Command


class InboxStatus(StrEnum):
    """Command 入队结果。receipt 是同步返回值，不是第二份持久真相。"""

    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    REJECTED_TERMINAL = "rejected_terminal"
    QUEUE_FULL = "queue_full"
    UNKNOWN_RUN = "unknown_run"


@dataclass(frozen=True, slots=True)
class InboxReceipt:
    """surface 可据此映射 HTTP/CLI 结果，但不能据此直接改 Domain_State。"""

    accepted: bool
    status: InboxStatus
    reason: str | None = None

    def __post_init__(self) -> None:
        # accepted 只允许成功接收；duplicate 是幂等成功但绝不再次 reduce。
        if self.accepted is not (self.status is InboxStatus.ACCEPTED):
            raise ValueError("InboxReceipt.accepted must be true only for accepted status")
        if self.status is not InboxStatus.ACCEPTED and not self.reason:
            raise ValueError("rejected or duplicate InboxReceipt requires a reason")


@runtime_checkable
class CommandInboxPort(Protocol):
    """active run 的唯一外部 Command 入口。"""

    async def submit(
        self,
        command: Command,
        *,
        source: str,
        idempotency_key: str,
    ) -> InboxReceipt:
        """按 run FIFO 接收 Command；重复/终态/队满必须返回明确 receipt。"""


__all__ = ["CommandInboxPort", "InboxReceipt", "InboxStatus"]
