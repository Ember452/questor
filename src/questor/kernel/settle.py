"""L2 settle_turn：turn 边界把「真实 user + 定稿 assistant」写回会话作用域记忆（B6；§6.4b）。

判据三条同时成立才写：
1. 本轮有**真实 user**（跳过 ``system_marker``/origin=seed 的种子消息）；
2. 有**定稿 assistant** 可见文本（tool-only 轮不写）；
3. **未被中断**（Interrupt 点的 verdict 由 loop 传入，不靠 run.status 反推）。

写路径：``WriteMemory`` 命令经唯一咽喉 ``apply`` → ``memory_written`` 事件经 ``bus.emit``
落到 ``run_id='sess:<id>'`` 的 session 流；再由本模块在消费点调 ``MemoryStorePort.write``
（与 loop 的 WriteMemory 消费点同纪律）。surface 不旁路直写。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace

from questor.contracts.events import WriteMemory
from questor.contracts.memory import MemoryScope, MemoryStorePort, MemoryWrite, MemoryWriteKind
from questor.state.domain_state import Run
from questor.state.transition import apply

_log = logging.getLogger("questor.settle")

#: 单次写回正文上限（与 reduce 的 16KiB 写上限同源；超限截断并带标记，不静默丢）。
MAX_SETTLE_BYTES = 16 * 1024


@dataclass(frozen=True, slots=True)
class TurnBoundary:
    """一次 turn 定稿的边界事实（Stop/Interrupt 点的产物，供 settle 判定）。"""

    run_id: str
    turn: int
    user_text: str | None
    assistant_text: str | None
    interrupted: bool
    usage: dict


def _bounded(text: str) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= MAX_SETTLE_BYTES:
        return text
    kept = raw[:MAX_SETTLE_BYTES].decode("utf-8", errors="ignore")
    return f"{kept}…[truncated {len(raw) - MAX_SETTLE_BYTES} bytes]"


class TurnSettler:
    """把 turn 边界写回 session 作用域；失败/超时只告警，绝不阻塞回复（§6.4b 失败语义）。"""

    def __init__(
        self,
        bus: object,
        store: object | None,
        memory_store: MemoryStorePort | None,
        session_id: str,
        *,
        timeout: float = 2.0,
    ) -> None:
        self.bus = bus
        self.store = store
        self.memory_store = memory_store
        self.session_id = session_id
        self.timeout = timeout
        self._settled: set[tuple[str, int]] = set()
        self._session_runs: dict[str, Run] = {}

    async def settle(self, boundary: TurnBoundary) -> bool:
        """返回是否真的写回；中断/无真实 user/无定稿 assistant/重复轮一律 False。"""
        if boundary.interrupted:
            return False
        if not boundary.user_text or not boundary.assistant_text:
            return False
        if self.memory_store is None:
            return False
        key = (boundary.run_id, boundary.turn)
        if key in self._settled:
            return False
        text = _bounded(f"user: {boundary.user_text}\nassistant: {boundary.assistant_text}")
        payload = MemoryWrite(
            kind=MemoryWriteKind.DAILY,
            scope=MemoryScope.SESSION,
            text=text,
            note="settle_turn",
        )
        try:
            await asyncio.wait_for(self._write(boundary, payload), timeout=self.timeout)
        except Exception:  # noqa: BLE001 - 记忆写是 best-effort：失败只告警，不阻塞回复
            _log.warning("settle_turn failed for run=%s turn=%s", boundary.run_id, boundary.turn, exc_info=True)
            return False
        self._settled.add(key)
        return True

    async def _write(self, boundary: TurnBoundary, payload: MemoryWrite) -> None:
        idem = f"settle:{boundary.run_id}:{boundary.turn}"
        session_run_id = f"sess:{self.session_id}"
        if self.store is not None and callable(getattr(self.store, "sequence_head", None)):
            head = await self.store.sequence_head(session_run_id)  # type: ignore[attr-defined]
            run = self._session_runs.get(self.session_id) or Run(run_id=session_run_id, seq=head)
            if run.seq < head:
                run = replace(run, seq=head)
            store = self.store
        else:
            run = self._session_runs.get(self.session_id) or Run(run_id=session_run_id)
            store = None
        applied = apply(
            store,  # type: ignore[arg-type]
            run,
            WriteMemory(run_id=session_run_id, payload=payload),
            source="settle",
            idempotency_key=idem,
        )
        new_run, events = applied  # Applied.__iter__（B2）与既有 2-tuple 都兼容
        self._session_runs[self.session_id] = new_run
        for env in events:
            await self.bus.emit(env)  # type: ignore[attr-defined]
        await self.memory_store.write(payload, idempotency_key=idem)  # type: ignore[union-attr]


__all__ = ["MAX_SETTLE_BYTES", "TurnBoundary", "TurnSettler"]
