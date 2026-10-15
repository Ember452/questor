"""L2 RunController / in-process Command Inbox（ADR-0013；HARD C16）。

这里只调度写意图，绝不 reduce、不持久化、不判权限。Command 被取出后仍由唯一 loop 消费者
串行交给 reduce；这样 surfaces 的并发提交不会制造第二写者。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass

from questor.contracts.events import Command
from questor.contracts.inbox import InboxReceipt, InboxStatus
from questor.state.domain_state import Run


@dataclass(frozen=True, slots=True)
class _QueuedCommand:
    """队列内部记录；digest 用于证明同一 idempotency key 是否指向同一意图。"""

    command: Command
    source: str
    idempotency_key: str
    digest: str


class RunController:
    """active run 的有界、FIFO Command Inbox。"""

    def __init__(self, run: Run, *, limit: int = 1024) -> None:
        if limit <= 0:
            raise ValueError("RunController.limit must be positive")
        self.run = run
        self._queue: asyncio.Queue[_QueuedCommand] = asyncio.Queue(maxsize=limit)
        # wait_for 可能先取出与当前等待条件无关的 Command。必须暂存而不是丢弃，
        # 否则 Cancel 会在只等 ResolveApproval 时被偷走。
        self._deferred: list[_QueuedCommand] = []
        self._seen_digests: dict[str, str] = {}
        self._closed = False
        self._lock = asyncio.Lock()

    def close(self) -> None:
        """终态后关闭入口；迟到 Command 只能得到 receipt，不能复活 run。"""
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed

    async def submit(
        self,
        command: Command,
        *,
        source: str,
        idempotency_key: str,
    ) -> InboxReceipt:
        """幂等地接收 Command；重复返回 duplicate，冲突/终态/队满均不写 queue。"""
        if self._closed:
            return InboxReceipt(accepted=False, status=InboxStatus.REJECTED_TERMINAL, reason="run inbox is closed")
        if not idempotency_key:
            return InboxReceipt(accepted=False, status=InboxStatus.REJECTED_TERMINAL, reason="idempotency_key is required")

        digest = repr(command)
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
            if self._queue.full():
                return InboxReceipt(accepted=False, status=InboxStatus.QUEUE_FULL, reason="run command queue is full")

            self._queue.put_nowait(_QueuedCommand(command, source, idempotency_key, digest))
            self._seen_digests[idempotency_key] = digest
            return InboxReceipt(accepted=True, status=InboxStatus.ACCEPTED)

    async def next_batch(self) -> tuple[Command, ...]:
        """按 FIFO 排空 deferred + live queue；调用方是 Command 的唯一消费者。"""
        async with self._lock:
            drained = [*self._deferred]
            self._deferred.clear()
            while True:
                try:
                    drained.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            return tuple(item.command for item in drained)

    async def wait_for(
        self,
        predicate: Callable[[Command], bool],
        timeout: float | None = None,
    ) -> Command | None:
        """等待匹配 Command；不匹配项暂存，确保不破坏 FIFO 与取消语义。"""
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
                queued = await asyncio.wait_for(self._queue.get(), timeout=remaining)
            except TimeoutError:
                return None
            if predicate(queued.command):
                return queued.command
            async with self._lock:
                self._deferred.append(queued)


__all__ = ["RunController"]
