"""P0 DoD —— 接口骨架上的构造不变式成立（design/01/02）。

只断言*形状*守卫；reduce/循环的运行时行为属 P1。
"""

from __future__ import annotations

from datetime import datetime

import pytest

from questor.capabilities.tools.read import ReadTool
from questor.contracts.common import new_id, validate_json_object
from questor.contracts.errors import ErrorEntry, ErrorKind, ErrorLayer, RecoveryHints
from questor.contracts.events import Cancel, Envelope
from questor.contracts.state_schema import (
    CLOSED_TOOL_CALL_STATUSES,
    OPEN_TOOL_CALL_STATUSES,
    ApprovalStatus,
    CancelReason,
    Message,
    Role,
    RunStatus,
    ToolArgsStatus,
    ToolCallStatus,
)
from questor.contracts.tool import Capability
from questor.state.domain_state import Run


def test_run_terminal_requires_completed_at() -> None:
    with pytest.raises(ValueError, match="completed_at"):
        Run(run_id=new_id("run"), status=RunStatus.COMPLETED)


def test_run_cancelled_requires_reason() -> None:
    ts = datetime.now()  # naive on purpose -> must fail ts check OR reason check first
    with pytest.raises(ValueError):
        Run(run_id=new_id("run"), status=RunStatus.CANCELLED, completed_at=ts)


def test_run_non_terminal_cannot_have_completed_at() -> None:
    with pytest.raises(ValueError, match="non-terminal"):
        Run(run_id=new_id("run"), status=RunStatus.RUNNING, completed_at=datetime.now())


def test_message_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        Message(
            id=new_id("msg"), role=Role.USER, content=(), seq=0, created_at=datetime(2020, 1, 1)
        )


def test_message_negative_seq_rejected() -> None:
    with pytest.raises(ValueError, match="Message.seq"):
        Message(id=new_id("msg"), role=Role.USER, content=(), seq=-1)


def test_envelope_negative_seq_rejected() -> None:
    with pytest.raises(ValueError, match="Envelope.seq"):
        Envelope(v=1, seq=-1, run_id=new_id("run"), type="run_started", data={})


def test_error_entry_rejects_naive_timestamp() -> None:
    hints = RecoveryHints(retryable=True)
    with pytest.raises(ValueError, match="timezone-aware"):
        ErrorEntry(
            kind=ErrorKind.TIMEOUT,
            layer=ErrorLayer.PROVIDER,
            message="boom",
            at_turn=1,
            hints=hints,
            timestamp=datetime(2020, 1, 1),
        )


def test_cancel_command_carries_reason() -> None:
    cmd = Cancel(run_id=new_id("run"), reason=CancelReason.NO_PROGRESS)
    assert cmd.type == "cancel"
    assert cmd.reason is CancelReason.NO_PROGRESS


def test_read_tool_is_readonly_capability() -> None:
    assert ReadTool.spec.name == "read"
    assert ReadTool.spec.read_only is True
    assert ReadTool.spec.capability is Capability.READONLY
    assert ReadTool.spec.parallel_safe is False  # placeholder only until P5


def test_validate_json_object_blocks_nan() -> None:
    with pytest.raises(ValueError, match="JSON-safe"):
        validate_json_object({"x": float("nan")}, "payload")


def test_p2_tool_call_lifecycle_locks_every_state() -> None:
    """P2 状态机必须可持久化，不能把审批/运行中状态退回为内存变量。"""
    assert {status.value for status in ToolCallStatus} == {
        "pending",
        "validated",
        "awaiting_approval",
        "ready",
        "running",
        "success",
        "error",
        "critical_error",
        "timed_out",
        "cancelled",
        "denied",
    }
    assert OPEN_TOOL_CALL_STATUSES == {
        ToolCallStatus.PENDING,
        ToolCallStatus.VALIDATED,
        ToolCallStatus.AWAITING_APPROVAL,
        ToolCallStatus.READY,
        ToolCallStatus.RUNNING,
    }
    assert CLOSED_TOOL_CALL_STATUSES == {
        ToolCallStatus.SUCCESS,
        ToolCallStatus.ERROR,
        ToolCallStatus.CRITICAL_ERROR,
        ToolCallStatus.TIMED_OUT,
        ToolCallStatus.CANCELLED,
        ToolCallStatus.DENIED,
    }
    assert not OPEN_TOOL_CALL_STATUSES & CLOSED_TOOL_CALL_STATUSES


def test_p2_contract_lifecycle_supports_args_and_approval_states() -> None:
    assert {status.value for status in ToolArgsStatus} == {"valid", "invalid", "missing"}
    assert {status.value for status in ApprovalStatus} == {
        "pending",
        "approved",
        "denied",
        "expired",
        "cancelled",
    }
