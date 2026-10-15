"""P2 新 L0 契约的构造不变式。

这些测试只锁“形状与失败口径”；真正入队/消费行为属 kernel tests。
"""

from __future__ import annotations

import pytest

from questor.contracts.events import Cancel
from questor.contracts.inbox import CommandInboxPort, InboxReceipt, InboxStatus
from questor.contracts.state_schema import CancelReason


def test_inbox_receipt_only_accepts_accepted_as_success() -> None:
    accepted = InboxReceipt(accepted=True, status=InboxStatus.ACCEPTED)
    duplicate = InboxReceipt(accepted=False, status=InboxStatus.DUPLICATE, reason="same idempotency key")
    assert accepted.accepted is True
    assert duplicate.status is InboxStatus.DUPLICATE
    with pytest.raises(ValueError, match="requires a reason"):
        InboxReceipt(accepted=False, status=InboxStatus.QUEUE_FULL)
    with pytest.raises(ValueError, match="must be true only"):
        InboxReceipt(accepted=True, status=InboxStatus.UNKNOWN_RUN, reason="bad")


def test_command_inbox_port_is_runtime_protocol() -> None:
    class _Inbox:
        async def submit(self, command, *, source, idempotency_key):  # noqa: ANN001, ANN202
            return InboxReceipt(accepted=True, status=InboxStatus.ACCEPTED)

    assert isinstance(_Inbox(), CommandInboxPort)
    assert Cancel(run_id="r", reason=CancelReason.USER)
