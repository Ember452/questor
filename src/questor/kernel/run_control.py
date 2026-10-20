"""L2 RunController / Command Inbox（ADR-0013；HARD C16）。

这里只调度写意图，绝不 reduce、不持久化、不判权限。Command 被取出后仍由唯一 loop 消费者
串行交给 reduce；这样 surfaces 的并发提交不会制造第二写者。

B3：``asyncio.Queue`` 只是**无 store 时的进程内回退**；注入 ``queue``（StorePort 的
``enqueue_submission`` 接口）后，提交先落 ``submissions`` 表（session 作用域），
``next_batch``/``wait_for`` 从表 claim，应用后再 ack。多进程写者只并发写队列表，
``event_log`` 仍只由持租约者 append。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass

from questor.contracts.events import (
    Cancel,
    Command,
    ExpireApproval,
    ResolveApproval,
    SetPermissionMode,
    SubmitMessage,
)
from questor.contracts.inbox import InboxReceipt, InboxStatus
from questor.contracts.state_schema import CancelReason
from questor.contracts.submissions import (
    SubmissionConflictError,
    SubmissionQueueFullError,
    command_digest,
    command_payload,
    kind_for_command,
)
from questor.state.domain_state import Run
from questor.state.snapshot import message_from_dict

#: 耐久模式 wait_for 的轮询间隔（跨进程写者无法用本地 Event 唤醒；20ms 足够快且不烧 CPU）。
_POLL_SECONDS = 0.02


@dataclass(frozen=True, slots=True)
class _QueuedCommand:
    """队列内部记录；digest 用于证明同一 idempotency key 是否指向同一意图。"""

    command: Command
    source: str
    idempotency_key: str
    digest: str


def _decode_command(payload: dict, run_id: str) -> Command:
    """把 submissions.payload 还原成 Command；run_id 以**当前消费的 run** 为准（路由）。"""
    ctype = payload.get("type")
    fields = payload.get("fields") or {}
    if ctype == SubmitMessage.type:
        return SubmitMessage(run_id=run_id, content=message_from_dict(fields["content"]))
    if ctype == ResolveApproval.type:
        return ResolveApproval(
            run_id=run_id,
            request_id=fields["request_id"],
            decision=fields["decision"],
            decided_by=fields["decided_by"],
        )
    if ctype == ExpireApproval.type:
        return ExpireApproval(run_id=run_id, request_id=fields["request_id"])
    if ctype == Cancel.type:
        return Cancel(run_id=run_id, reason=CancelReason(fields["reason"]))
    if ctype == SetPermissionMode.type:
        return SetPermissionMode(run_id=run_id, mode=fields["mode"], changed_by=fields["changed_by"])
    raise ValueError(f"submission payload has unknown command type {ctype!r}")


class RunController:
    """active run 的有界、FIFO Command Inbox。"""

    def __init__(
        self,
        run: Run,
        *,
        limit: int = 1024,
        queue: object | None = None,
        session_id: str | None = None,
    ) -> None:
        if limit <= 0:
            raise ValueError("RunController.limit must be positive")
        self.run = run
        self._queue = queue if callable(getattr(queue, "enqueue_submission", None)) else None
        self.session_id = session_id or (f"sess:{run.run_id}" if self._queue is not None else None)
        self._queue_limit = limit
        self._queue_impl: asyncio.Queue[_QueuedCommand] = asyncio.Queue(maxsize=limit)
        # wait_for 可能先取出与当前等待条件无关的 Command。必须暂存而不是丢弃，
        # 否则 Cancel 会在只等 ResolveApproval 时被偷走。
        self._deferred: list[_QueuedCommand] = []
        self._seen_digests: dict[str, str] = {}
        # 耐久模式：id(command) -> item_id（ack 时回收；命令对象由 next_batch/wait_for 原样返回）。
        self._claimed: dict[int, str] = {}
        self._closed = False
        self._lock = asyncio.Lock()

    def close(self) -> None:
        """终态后关闭入口；迟到 Command 只能得到 receipt，不能复活 run。"""
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def durable(self) -> bool:
        """是否走 submissions 表（False = 进程内回退）。"""
        return self._queue is not None

    async def submit(
        self,
        command: Command,
        *,
        source: str,
        idempotency_key: str,
        kind: str | None = None,
    ) -> InboxReceipt:
        """幂等地接收 Command；重复返回 duplicate，冲突/终态/队满均不写 queue。"""
        if self._closed:
            return InboxReceipt(accepted=False, status=InboxStatus.REJECTED_TERMINAL, reason="run inbox is closed")

        if self._queue is not None:
            digest = command_digest(command)
            kind_value = kind or kind_for_command(command)
            key = idempotency_key or f"auto:{kind_value}:{digest}"  # 无 id 时 fail-open：宁可重复一条，不可丢一条
            try:
                result = await self._queue.enqueue_submission(  # type: ignore[attr-defined]
                    self.session_id,
                    kind_value,
                    command_payload(command),
                    source=source,
                    idem_key=key,
                    digest=digest,
                    run_id=self.run.run_id,
                )
            except SubmissionConflictError as exc:
                return InboxReceipt(accepted=False, status=InboxStatus.REJECTED_TERMINAL, reason=str(exc))
            except SubmissionQueueFullError as exc:
                return InboxReceipt(accepted=False, status=InboxStatus.QUEUE_FULL, reason=str(exc))
            if result.get("duplicate"):
                return InboxReceipt(accepted=False, status=InboxStatus.DUPLICATE, reason="duplicate idempotency key")
            return InboxReceipt(accepted=True, status=InboxStatus.ACCEPTED)

        if not idempotency_key:
            return InboxReceipt(accepted=False, status=InboxStatus.REJECTED_TERMINAL, reason="idempotency_key is required")

        digest = command_digest(command)
        async with self._lock:
            previous = self._seen_digests.get(idempotency_key)
            if previous == digest:
                return InboxReceipt(accepted=False, status=InboxStatus.DUPLICATE, reason="duplicate idempotency key")
            if previous is not None:
                return InboxReceipt(
                    accepted=False,
                    status=InboxStatus.REJECTED_TERMINAL,
                    reason="idempotency key already bound to a different command",
                )
            if self._queue_impl.full():
                return InboxReceipt(accepted=False, status=InboxStatus.QUEUE_FULL, reason="run command queue is full")

            self._queue_impl.put_nowait(_QueuedCommand(command, source, idempotency_key, digest))
            self._seen_digests[idempotency_key] = digest
            return InboxReceipt(accepted=True, status=InboxStatus.ACCEPTED)

    async def next_batch(self) -> tuple[Command, ...]:
        """按 FIFO 排空 deferred + live queue；调用方是 Command 的唯一消费者。"""
        if self._queue is not None:
            rows = await self._queue.claim_submissions(  # type: ignore[attr-defined]
                self.session_id, limit=self._queue_limit, run_id=self.run.run_id
            )
            if not rows:
                return ()
            try:
                commands = tuple(_decode_command(row["payload"], self.run.run_id) for row in rows)
            except BaseException:
                await self._queue.release_submissions(tuple(row["item_id"] for row in rows))  # type: ignore[attr-defined]
                raise
            for row, command in zip(rows, commands, strict=True):
                self._claimed[id(command)] = row["item_id"]
            return commands

        async with self._lock:
            drained = [*self._deferred]
            self._deferred.clear()
            while True:
                try:
                    drained.append(self._queue_impl.get_nowait())
                except asyncio.QueueEmpty:
                    break
            return tuple(item.command for item in drained)

    async def ack(self, batch: tuple[Command, ...]) -> None:
        """应用成功后确认 consumed；进程内模式为 no-op。"""
        if self._queue is None or not batch:
            return
        item_ids = tuple(self._claimed.pop(id(command), "") for command in batch)
        await self._queue.ack_submissions(tuple(item_id for item_id in item_ids if item_id))  # type: ignore[attr-defined]

    async def ack_one(self, command: Command) -> None:
        """确认单条命令（审批等待路径）。"""
        await self.ack((command,))

    async def wait_for(
        self,
        predicate: Callable[[Command], bool],
        timeout: float | None = None,
    ) -> Command | None:
        """等待匹配 Command；不匹配项暂存，确保不破坏 FIFO 与取消语义。"""
        if self._queue is not None:
            deadline = None if timeout is None else time.monotonic() + timeout
            while True:
                rows = await self._queue.claim_submissions(  # type: ignore[attr-defined]
                    self.session_id, limit=100, run_id=self.run.run_id
                )
                if rows:
                    try:
                        decoded = [(_decode_command(row["payload"], self.run.run_id), row) for row in rows]
                    except BaseException:
                        await self._queue.release_submissions(tuple(row["item_id"] for row in rows))  # type: ignore[attr-defined]
                        raise
                    unmatched = tuple(row["item_id"] for command, row in decoded if not predicate(command))
                    if unmatched:
                        await self._queue.release_submissions(unmatched)  # type: ignore[attr-defined]
                    for command, row in decoded:
                        if predicate(command):
                            self._claimed[id(command)] = row["item_id"]
                            return command
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return None
                await asyncio.sleep(_POLL_SECONDS if remaining is None else min(_POLL_SECONDS, max(0.0, remaining)))

        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            async with self._lock:
                for index, queued in enumerate(self._deferred):
                    if predicate(queued.command):
                        return self._deferred.pop(index).command
            remaining = None
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
            try:
                queued = await asyncio.wait_for(self._queue_impl.get(), timeout=remaining)
            except TimeoutError:
                return None
            if predicate(queued.command):
                return queued.command
            async with self._lock:
                self._deferred.append(queued)


__all__ = ["RunController"]
