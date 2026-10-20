"""最小调度器实现（B11；v3 §9）：occurrences/executions + 所有权 + 配额挂起 + 防互刷。"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime

from questor.contracts.common import new_id
from questor.contracts.events import SubmitMessage
from questor.contracts.state_schema import ContentBlock, Message, Role
from questor.contracts.submissions import command_digest, command_payload

_log = logging.getLogger("questor.schedule")

#: 一次触发/执行的因果身份（带进事件与日志；测试可经 current_execution_identity 读取）。
_EXECUTION_ID: ContextVar[str | None] = ContextVar("questor_execution_identity", default=None)

#: 所有权 lease 的 run_id 位（复用 run_leases，不新建锁表）。
_OWNER_ID = "sched:main"


def current_execution_identity() -> str | None:
    """当前 tick 的 execution_id；不在 tick 内为 None。"""
    return _EXECUTION_ID.get()


@dataclass(frozen=True, slots=True)
class ScheduleSpec:
    """一条调度定义（测试/宿主创建时用；存储由 store 的 schedules 表承载）。"""

    schedule_id: str
    session_id: str
    subject: str
    text: str
    interval_seconds: float
    next_run_at: float


class Scheduler:
    """最小完备 E 环：tick 由 serve 后台任务/测试驱动；不持有自己的写入口。"""

    def __init__(
        self,
        store: object,
        *,
        quota_remaining: Callable[[], int | None] | None = None,
        max_per_hour: int = 6,
        quota_retry_seconds: float = 3600.0,
        interval_seconds: float = 30.0,
        ownership_ttl: float = 60.0,
    ) -> None:
        self.store = store
        self.quota_remaining = quota_remaining
        self.max_per_hour = max_per_hour
        self.quota_retry_seconds = quota_retry_seconds
        self.interval_seconds = interval_seconds
        self.ownership_ttl = ownership_ttl
        self._holder = f"sched:{os.getpid()}:{time.monotonic():.3f}"

    async def tick(self, now: float | None = None) -> dict[str, int]:
        """跑一次 tick：拿所有权 → 逐 due → 静默/防互刷/配额闸 → 仅经 submissions 入队。"""
        stamp = time.time() if now is None else now
        if not await self.store.acquire_lease(_OWNER_ID, self._holder, 1, self.ownership_ttl):  # type: ignore[attr-defined]
            return {"fired": 0, "skipped": 0, "held": 0}
        fired = skipped = held = 0
        try:
            for spec in await self.store.due_schedules(stamp):  # type: ignore[attr-defined]
                due_at = float(spec["next_run_at"])
                schedule_id = str(spec["schedule_id"])
                session_id = str(spec["session_id"])
                subject = str(spec["subject"])
                execution_id = f"sched:{schedule_id}:{due_at}"
                token = _EXECUTION_ID.set(execution_id)
                try:
                    today = datetime.fromtimestamp(stamp).date().isoformat()
                    if await self.store.session_quiet(session_id) == today:  # type: ignore[attr-defined]
                        await self._skip(schedule_id, due_at, stamp, execution_id, spec)
                        skipped += 1
                        continue
                    recent = await self.store.count_executions(session_id, subject, stamp - 3600)  # type: ignore[attr-defined]
                    if recent >= self.max_per_hour:  # bot_loop_guard：同会话同主体每小时上限
                        await self._skip(schedule_id, due_at, stamp, execution_id, spec)
                        skipped += 1
                        continue
                    if self.quota_remaining is not None:
                        remaining = self.quota_remaining()
                        if remaining is not None and remaining <= 0:
                            # 配额挂起：新 occurrence 停在恢复边界，不补跑 N 次
                            await self.store.mark_occurrence(schedule_id, due_at, "skipped", fired_at=stamp, execution_id=execution_id)  # type: ignore[attr-defined]
                            await self.store.advance_schedule(schedule_id, stamp + self.quota_retry_seconds)  # type: ignore[attr-defined]
                            held += 1
                            continue
                    message = Message(
                        id=new_id("msg"),
                        role=Role.USER,
                        content=(ContentBlock(type="text", text=str(spec["text"])),),
                        seq=0,
                    )
                    command = SubmitMessage(run_id="", content=message)  # run_id 由消费端绑定
                    await self.store.enqueue_submission(  # type: ignore[attr-defined]
                        session_id,
                        "user_message",
                        command_payload(command),
                        source="scheduler",
                        idem_key=execution_id,
                        digest=command_digest(command),
                    )
                    await self.store.mark_occurrence(schedule_id, due_at, "fired", fired_at=stamp, execution_id=execution_id)  # type: ignore[attr-defined]
                    await self.store.record_execution(  # type: ignore[attr-defined]
                        execution_id, schedule_id, due_at, session_id, subject, "fired", stamp
                    )
                    await self.store.advance_schedule(schedule_id, due_at + float(spec["interval_seconds"]))  # type: ignore[attr-defined]
                    fired += 1
                finally:
                    _EXECUTION_ID.reset(token)
        finally:
            await self.store.release_lease(_OWNER_ID, self._holder, 1)  # type: ignore[attr-defined]
        return {"fired": fired, "skipped": skipped, "held": held}

    async def _skip(self, schedule_id: str, due_at: float, stamp: float, execution_id: str, spec: dict) -> None:
        await self.store.mark_occurrence(schedule_id, due_at, "skipped", fired_at=stamp, execution_id=execution_id)  # type: ignore[attr-defined]
        await self.store.advance_schedule(schedule_id, due_at + float(spec["interval_seconds"]))  # type: ignore[attr-defined]

    async def run_forever(self) -> None:
        """serve 后台任务：周期 tick；单次故障只告警，不退出（调度失败不阻塞服务）。"""
        while True:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 - 调度故障不得带崩 sidecar
                _log.warning("scheduler tick failed", exc_info=True)
            await asyncio.sleep(self.interval_seconds)


__all__ = ["ScheduleSpec", "Scheduler", "current_execution_identity"]
