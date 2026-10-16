"""L2 内部事件总线 + 对外投影 + 版本闸门（design/02；C5/C6/C13）。

loop 把 ``reduce`` 产出的 ``Envelope`` 经 ``emit`` 推入总线。总线职责：
- 将可持久事件落库（live-only delta 只转发、永不入库——design/01 I3 / design/02 X2）；
- 内部→对外投影并丢弃未知类型，但未知错误类事件一定告警（C6）；
- 强制终态唯一（first-writer-wins），一个 run 恰传一个终态（C13）；
- 从 ``after_seq`` 重放后再无缝跟实时（不丢不重，02 §4）。

版本不匹配的订阅者只会收到一条 ``resync_required`` 然后停（不做跨版本解码，02 §10）。"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import datetime

from questor.contracts.events import (
    EVENT_SCHEMA_VERSION,
    Envelope,
    EventType,
)
from questor.contracts.ports import StorePort

_log = logging.getLogger("questor.bus")

#: live-only 事件：只转发给订阅者、永不持久化（design/01 I3）。
LIVE_ONLY: frozenset[str] = frozenset(
    {EventType.TEXT_DELTA, EventType.REASONING_DELTA, EventType.TOOL_PROGRESS, EventType.HEARTBEAT, EventType.USAGE_DELTA}
)
# 终态事件：一轮至多一个（C13）。
TERMINAL: frozenset[str] = frozenset({EventType.RUN_CANCELLED, EventType.RUN_FAILED, EventType.RUN_COMPLETED})
#: 仅内部、不在对外契约的事件（私有、可演进；投影时会滤掉，design/02 §2）。
INTERNAL_ONLY: frozenset[str] = frozenset({"checkpoint_recorded", "reduce_rejected", "ledger_entry"})


#: 每个对外事件的 data 白名单字段（design/02 §3/§5；ADR-0019）。只有列出的键才会
#: 进入外部 Envelope：完整 args、abs path、env values、provider state 都不在白名单，默认不外发。
#: 值为 ``None`` 表示该类型的 data 原样透传（仅用于尚未定形的 node_updated）。
EXTERNAL_EVENT_FIELDS: dict[str, frozenset[str] | None] = {
    EventType.RUN_STARTED: frozenset({"run_id"}),
    EventType.TURN_STARTED: frozenset({"turn"}),
    EventType.TEXT_DELTA: frozenset({"delta", "item_id"}),
    EventType.REASONING_DELTA: frozenset({"delta"}),
    EventType.MESSAGE_COMPLETED: frozenset({"message_id"}),
    EventType.TOOL_STARTED: frozenset({"tool_call_id", "name", "capability", "risk", "args_summary"}),
    EventType.TOOL_PROGRESS: frozenset({"message"}),
    EventType.TOOL_COMPLETED: frozenset({"tool_call_id", "status"}),
    EventType.APPROVAL_REQUEST: frozenset({"request_id", "tool_call_id", "name", "args_summary", "risk", "reason", "expires_at"}),
    EventType.APPROVAL_RESOLVED: frozenset({"request_id", "tool_call_id", "decision", "decided_by", "resolved_at"}),
    EventType.PERMISSION_MODE_CHANGED: frozenset({"mode", "changed_by", "effective_from_turn"}),
    EventType.NODE_UPDATED: None,
    EventType.USAGE_DELTA: frozenset({"input_tokens", "output_tokens", "total_tokens"}),
    EventType.HEARTBEAT: frozenset(),
    EventType.RUN_CANCELLED: frozenset({"reason"}),
    EventType.RUN_FAILED: frozenset({"error"}),
    EventType.RUN_COMPLETED: frozenset({"usage", "exit_reason"}),
    EventType.RESYNC_REQUIRED: frozenset({"reason", "expected", "current"}),
    EventType.WARNING: frozenset({"message"}),
    EventType.MEMORY_WRITTEN: frozenset({"kind", "chunk_count", "source", "artifact_ref"}),
}


def project(env: Envelope) -> Envelope | None:
    """将内部事件投影为对外集：丢弃内部类型，并按 per-type 白名单过滤 data 字段。"""
    if env.type in INTERNAL_ONLY:
        return None
    allowed = EXTERNAL_EVENT_FIELDS.get(env.type)
    if allowed is None:
        # 未知外部类型：错误类告警保留，其余静默忽略（C6）。
        from questor.contracts.events import ERROR_CLASS_EVENT_TYPES

        return env if env.type in ERROR_CLASS_EVENT_TYPES else None
    if allowed == frozenset():
        return replace(env, data={})
    data = {k: v for k, v in env.data.items() if k in allowed}
    return replace(env, data=data)


class EventBus(ABC):
    @abstractmethod
    async def emit(self, env: Envelope) -> None: ...

    @abstractmethod
    def subscribe(
        self, run_id: str, after_seq: int = 0, *, expected_version: int | None = None
    ) -> AsyncIterator[Envelope]: ...


class InProcessEventBus(EventBus):
    """单进程内存总线：用 asyncio.Queue 向订阅者扇出；可注入 store 做持久/重放。"""

    def __init__(self, store: StorePort | None = None) -> None:
        self._store = store
        self._subs: dict[str, list[asyncio.Queue[Envelope]]] = defaultdict(list)
        self._closed: set[str] = set()

    def add_subscriber(self, run_id: str) -> asyncio.Queue[Envelope]:
        queue: asyncio.Queue[Envelope] = asyncio.Queue()
        self._subs[run_id].append(queue)
        return queue

    async def emit(self, env: Envelope) -> None:
        """落库（非 live-only）→投影后向订阅者转发；终态至多一条。"""
        if env.type in TERMINAL:
            if env.run_id in self._closed:  # first-writer-wins：已终态则丢弃后续
                return
            self._closed.add(env.run_id)

        if env.type not in LIVE_ONLY and self._store is not None:
            try:
                await self._store.append(
                    env.run_id,
                    ({"seq": env.seq, "type": env.type, "turn": env.turn, "data": dict(env.data), "ts": env.ts.isoformat()},),
                )
            except Exception as exc:  # noqa: BLE001 - 持久化失败出声后上冒：数据丢失不可静默吞，保持既有致命语义
                _log.warning("bus persist failed run=%s seq=%s: %s", env.run_id, env.seq, exc)
                raise

        projected = project(env)
        if projected is None:
            return
        for queue in self._subs.get(env.run_id, ()):
            try:
                queue.put_nowait(projected)
            except asyncio.QueueFull:  # 背压丢帧：慢消费者可 resync，出声但不拖垮 loop（DoD A②）
                _log.warning("bus subscriber queue full, dropped frame run=%s seq=%s", env.run_id, env.seq)
        if env.type in TERMINAL:
            self._subs.pop(env.run_id, None)  # run 已结束：释放订阅队列（防泄漏）。
            # 保留 _closed：它是“抑制本 run 后续任何终态”的记忆（C13），只存短 run id。

    async def subscribe(
        self, run_id: str, after_seq: int = 0, *, expected_version: int | None = None
    ) -> AsyncIterator[Envelope]:
        """先（版本闸门后）重放 after_seq 之后的可持久事件，再无缺口地跟实时，直到终态。"""
        if expected_version is not None and expected_version != EVENT_SCHEMA_VERSION:
            yield Envelope(v=EVENT_SCHEMA_VERSION, seq=after_seq, run_id=run_id, type=EventType.RESYNC_REQUIRED,
                           data={"reason": "version_mismatch", "expected": expected_version, "current": EVENT_SCHEMA_VERSION})
            return

        queue = self.add_subscriber(run_id)  # 先订阅后重放，避免两路之间的缺口
        seen = after_seq

        if self._store is not None:
            for row in await self._store.replay(run_id, after_seq):
                seen = max(seen, row["seq"])
                replayed = project(_row_to_envelope(run_id, row))
                if replayed is None:  # 仅内部：持久了但不外发
                    continue
                yield replayed
                if replayed.type in TERMINAL:  # run 已结束，无需再跟实时
                    return

        while True:
            env = await queue.get()
            if env.type in LIVE_ONLY:
                yield env  # 瞬态 delta：总是转发、不做 seq 去重
            elif env.seq > seen:
                seen = env.seq
                yield env
            if env.type in TERMINAL:
                break


def _row_to_envelope(run_id: str, row: dict) -> Envelope:
    """把 store 重放的一行还原成 Envelope（ts 从 ISO 字符串解析）。"""
    ts = row.get("ts")
    return Envelope(
        v=EVENT_SCHEMA_VERSION,
        seq=row["seq"],
        run_id=run_id,
        type=row["type"],
        turn=row.get("turn"),
        data=row.get("data", {}),
        ts=datetime.fromisoformat(ts) if ts else datetime.now(),
    )
