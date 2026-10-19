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
from collections.abc import AsyncIterator, Callable
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
    {EventType.TEXT_DELTA, EventType.REASONING_DELTA, EventType.TOOL_PROGRESS, EventType.HEARTBEAT, EventType.USAGE_DELTA, EventType.TOOLS_CHANGED}
)
# 终态事件：一轮至多一个（C13）。
TERMINAL: frozenset[str] = frozenset({EventType.RUN_CANCELLED, EventType.RUN_FAILED, EventType.RUN_COMPLETED})
#: 仅内部、不在对外契约的事件（私有、可演进；投影时会滤掉，design/02 §2）。
INTERNAL_ONLY: frozenset[str] = frozenset({"checkpoint_recorded", "reduce_rejected", "ledger_entry"})


#: 每个对外事件的 data 白名单字段（design/02 §3/§5；ADR-0019）。只有列出的键才会
#: 进入外部 Envelope：完整 args、abs path、env values、provider state 都不在白名单，默认不外发。
#: 注：`project` 对"不在本表 / 值为 None"的类型均按"未知外部类型"处理（错误类保留、余下丢弃）；
#: 故任何要外发的类型都必须在表里给显式白名单 frozenset（P7 T11 已把 draft 的 node_updated 定为此）。
EXTERNAL_EVENT_FIELDS: dict[str, frozenset[str] | None] = {
    EventType.RUN_STARTED: frozenset({"run_id", "policy_ref"}),  # policy_ref additive（P9/ADR-0045）；None/缺字段被 project 过滤
    EventType.TURN_STARTED: frozenset({"turn"}),
    EventType.TEXT_DELTA: frozenset({"delta", "item_id"}),
    EventType.REASONING_DELTA: frozenset({"delta"}),
    # 重连定稿正文（D-P7-C 选型①；ADR-0034）：additive 有界 final_text + item_id（单一真源，不另开 /transcript）。
    # final_text 只进事件协议，绝不进带外投影白名单（projection._DATA_KEYS 不含，C20）。
    EventType.MESSAGE_COMPLETED: frozenset({"message_id", "item_id", "final_text", "truncated"}),
    EventType.TOOL_STARTED: frozenset({"tool_call_id", "name", "capability", "risk", "args_summary"}),
    EventType.TOOL_PROGRESS: frozenset({"message"}),
    # 工具卡（P7 T7）additive：有界 preview + artifact 指针 + truncated（C18/C20；ADR-0035）。
    # preview/artifact_ref 只进事件协议（给前端），绝不进带外投影白名单（projection._DATA_KEYS 不含）。
    EventType.TOOL_COMPLETED: frozenset({"tool_call_id", "status", "preview", "artifact_ref", "truncated"}),
    EventType.APPROVAL_REQUEST: frozenset({"request_id", "tool_call_id", "name", "args_summary", "risk", "reason", "expires_at"}),
    EventType.APPROVAL_RESOLVED: frozenset({"request_id", "tool_call_id", "decision", "decided_by", "resolved_at"}),
    EventType.PERMISSION_MODE_CHANGED: frozenset({"mode", "changed_by", "effective_from_turn"}),
    # node_updated（任务树/DAG 属 P8，当前无生产者）：P7 T11 additive 定形为有界白名单，
    # 去"None 透传"隐患——一旦 P8 产出富节点，也不会把 prompt/result 类载荷原样外发（C18/C13）。
    EventType.NODE_UPDATED: frozenset({"node_id", "status", "title", "parent_id"}),
    EventType.USAGE_DELTA: frozenset({"input_tokens", "output_tokens", "total_tokens"}),
    EventType.HEARTBEAT: frozenset(),
    EventType.RUN_CANCELLED: frozenset({"reason"}),
    EventType.RUN_FAILED: frozenset({"error"}),
    EventType.RUN_COMPLETED: frozenset({"usage", "exit_reason"}),
    EventType.RESYNC_REQUIRED: frozenset({"reason", "expected", "current"}),
    EventType.WARNING: frozenset({"message"}),
    EventType.MEMORY_WRITTEN: frozenset({"kind", "chunk_count", "source", "artifact_ref"}),
    # peer_started/peer_ended（P8 子 agent，ADR-0042）：只关联键 + 有界终态 + artifact 指针，无正文（C18/C20）。
    # 注：两者均不进 projection._DATA_KEYS（C20：日得不复制载荷）。
    EventType.PEER_STARTED: frozenset({"parent_run_id", "child_run_id", "node_id"}),
    EventType.PEER_ENDED: frozenset({"parent_run_id", "child_run_id", "node_id", "terminal_status", "result_ref", "resumable_hint"}),
    # tools_changed（P9/ADR-0046）：live-only 能力名册变更告警，只一个 domain 枚举、无任何正文（C18/C20）。
    EventType.TOOLS_CHANGED: frozenset({"domain"}),
    # compact_started/compact_applied（P10/ADR-0048，design/02 §10）：只带栅栏/有界量、无正文（C18/C20）。
    # baseline_seq 供渲染侧重折上下文视图；不进 projection._DATA_KEYS（摘要文本属载荷、日得不复制，C20）。
    EventType.COMPACT_STARTED: frozenset({"reason"}),
    EventType.COMPACT_APPLIED: frozenset({"baseline_seq", "covered_from", "covered_to", "summary_bytes"}),
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
        # bus 级只读 observer（ADR-0033 / D-P7-A）：每条**投影后**的对外 Envelope 恰触发一次，
        # 与消费者/订阅者数量无关——带外投影（log_envelope）由此挂载，杜绝"逐消费者各投 = 多 surface 双投"。
        # 依赖方向：observer 由 surfaces/组合根注入回调，kernel 不 import observability（S7 九内核零依赖不破）。
        self._observers: list[Callable[[Envelope], None]] = []

    def add_observer(self, observer: Callable[[Envelope], None]) -> None:
        """挂一个只读 observer：每次 ``emit`` 对投影后的 Envelope 调用一次（旁路观测，不改状态/扇出）。"""
        self._observers.append(observer)

    def add_subscriber(self, run_id: str) -> asyncio.Queue[Envelope]:
        queue: asyncio.Queue[Envelope] = asyncio.Queue()
        self._subs[run_id].append(queue)
        return queue

    def _remove_subscriber(self, run_id: str, queue: asyncio.Queue[Envelope]) -> None:
        """从 ``_subs`` 摘掉一个队列；该 run 已无订阅者则连键一起清（防长驻 sidecar 泄漏）。"""
        queues = self._subs.get(run_id)
        if queues is not None and queue in queues:
            queues.remove(queue)
            if not queues:
                del self._subs[run_id]

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
        # 先触发 bus 级 observer（带外投影）：恰一次，与下面订阅扇出/订阅者数量无关（ADR-0033）。
        for observer in self._observers:
            observer(projected)
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

        # 分因闸门（§6-8）：after_seq 超过当前 durable 头 = 请求了尚未产生的游标（ahead），
        # 不静默空重放，而是发一条 resync_required 让客户端重新对齐（错误类必出声，C6）。
        if self._store is not None:
            head = await self._store.sequence_head(run_id)
            if after_seq > head:
                yield Envelope(v=EVENT_SCHEMA_VERSION, seq=head, run_id=run_id, type=EventType.RESYNC_REQUIRED,
                               data={"reason": "after_ahead", "expected": after_seq, "current": head})
                return

        queue = self.add_subscriber(run_id)  # 先订阅后重放，避免两路之间的缺口
        seen = after_seq
        try:
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
        finally:
            # 无论重放到终态 return、正常 break、还是客户端断连（GeneratorExit/取消），
            # 都必须摘掉本次队列——否则常驻 sidecar 每次断连漏一个队列（track surfaces MAJ-1）。
            self._remove_subscriber(run_id, queue)


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
