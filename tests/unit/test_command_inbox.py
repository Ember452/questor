"""RunController 的 Command Inbox 串行/幂等/背压语义（ADR-0013）。"""

from __future__ import annotations

import asyncio

from questor.contracts.common import new_id
from questor.contracts.events import Cancel, ResolveApproval
from questor.contracts.inbox import InboxStatus
from questor.contracts.state_schema import CancelReason, RunStatus
from questor.kernel.run_control import RunController
from questor.state.domain_state import Run


def _run() -> Run:
    return Run(run_id=new_id("run"), status=RunStatus.RUNNING)


def _cancel(reason: CancelReason = CancelReason.USER) -> Cancel:
    return Cancel(run_id="run", reason=reason)


async def test_inbox_accepts_commands_in_fifo_order() -> None:
    controller = RunController(_run())
    first = _cancel(CancelReason.SAFETY)
    second = _cancel(CancelReason.TIMEOUT)
    assert (await controller.submit(first, source="test", idempotency_key="1")).status is InboxStatus.ACCEPTED
    assert (await controller.submit(second, source="test", idempotency_key="2")).status is InboxStatus.ACCEPTED
    assert await controller.next_batch() == (first, second)


async def test_duplicate_idempotency_key_with_same_command_is_no_op() -> None:
    controller = RunController(_run())
    command = _cancel()
    receipt = await controller.submit(command, source="test", idempotency_key="same")
    duplicate = await controller.submit(command, source="test", idempotency_key="same")
    assert receipt.accepted is True
    assert duplicate.status is InboxStatus.DUPLICATE
    assert await controller.next_batch() == (command,)


async def test_same_idempotency_key_with_different_command_is_rejected() -> None:
    controller = RunController(_run())
    first = _cancel(CancelReason.SAFETY)
    conflict = _cancel(CancelReason.TIMEOUT)
    await controller.submit(first, source="test", idempotency_key="same")
    receipt = await controller.submit(conflict, source="test", idempotency_key="same")
    assert receipt.status is InboxStatus.REJECTED_TERMINAL
    assert "idempotency key" in (receipt.reason or "")
    assert await controller.next_batch() == (first,)


async def test_closed_inbox_rejects_late_commands() -> None:
    controller = RunController(_run())
    controller.close()
    receipt = await controller.submit(_cancel(), source="test", idempotency_key="late")
    assert receipt.status is InboxStatus.REJECTED_TERMINAL
    assert await controller.next_batch() == ()


async def test_inbox_applies_backpressure_without_dropping() -> None:
    controller = RunController(_run(), limit=1)
    first = await controller.submit(_cancel(), source="test", idempotency_key="1")
    second = await controller.submit(_cancel(), source="test", idempotency_key="2")
    assert first.accepted is True
    assert second.status is InboxStatus.QUEUE_FULL
    assert await controller.next_batch() == (_cancel(),)


async def test_wait_for_preserves_non_matching_commands_for_later_drain() -> None:
    controller = RunController(_run())
    unrelated = _cancel()
    await controller.submit(unrelated, source="test", idempotency_key="unrelated")

    def is_resolve(command: object) -> bool:
        return isinstance(command, ResolveApproval)

    late = ResolveApproval(run_id="run", request_id="apr", decision="allow", decided_by="test")
    async def submit_later() -> None:
        await asyncio.sleep(0.01)
        await controller.submit(late, source="test", idempotency_key="late")

    task = asyncio.create_task(submit_later())
    received = await controller.wait_for(is_resolve, timeout=1)
    await task
    assert received is late
    assert await controller.next_batch() == (unrelated,)


async def test_wait_for_times_out_without_consuming_unrelated_command() -> None:
    controller = RunController(_run())
    unrelated = _cancel()
    await controller.submit(unrelated, source="test", idempotency_key="unrelated")

    def never(command: object) -> bool:
        return False

    assert await controller.wait_for(never, timeout=0.01) is None
    assert await controller.next_batch() == (unrelated,)
