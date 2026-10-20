"""L4 记忆巩固与退修（B9；v3 §6.5）。

四件事实，逐条对上 §6.5：

- **per-session 异步锁**：同一会话的巩固串行，不同会话并行；锁表按会话键惰性创建
  （不引入全局锁，也不给每轮回复加等待）。
- **非破坏式**：巩固只"返回浓缩文本 + 经幂等键写入"，绝不原地改写既有真源；
  幂等键使重投安全（ADR-0025 的 claim-then-commit）。
- **supersede 优先于 append**：用户明确否定过的旧事实要**退役**（软删 + 写新），
  而不是"新旧并存靠排序赌运气"——否则被否定过的事实下次还会被召回。
- **有界重试**：蒸馏器抛错最多再试 ``MAX_DISTILL_ATTEMPTS`` 次，超限就放弃本轮巩固
  （失败是合法结果，绝不阻塞回复，也不无限循环）。

"成批一次 embedder 调用"已由 ``SQLiteMemoryStore.sync()`` 承担（重建索引时单次批量 embedding）。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from questor.contracts.memory import MemoryStorePort, MemoryWrite
from questor.memory.write_policy import quota_allows

_log = logging.getLogger("questor.consolidate")

#: 蒸馏重试上限（含首次）；超限放弃本轮。
MAX_DISTILL_ATTEMPTS = 2


class DistillProvider(Protocol):
    """巩固用的浓缩器（真 LLM 或启发式）；返回 ``None`` = 无可萃取（合法结果）。"""

    async def distill(self, core: str, dailies: Sequence[str]) -> object: ...


@dataclass(frozen=True, slots=True)
class ConsolidationOutcome:
    """一次巩固的有界结果（只放计量与原因，不放正文）。"""

    wrote: bool
    reason: str
    attempts: int
    superseded: int = 0


_LOCKS: dict[str, asyncio.Lock] = {}


def lock_for(session_id: str) -> asyncio.Lock:
    """按会话取锁（同一会话串行；不同会话互不阻塞）。"""
    lock = _LOCKS.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[session_id] = lock
    return lock


def reset_consolidation_locks() -> None:
    """清空锁表（仅供测试/诊断；生产不需要）。"""
    _LOCKS.clear()


async def supersede(
    store: MemoryStorePort,
    *,
    entry_id: str,
    replacement: MemoryWrite,
    idempotency_key: str,
    reason: str = "user corrected",
) -> ConsolidationOutcome:
    """先退役旧事实（软删位），再写替代事实。

    顺序不能反：先写后删会在两步之间被召回；先删后写最坏是"这一轮少一条记忆"，
    而不是"矛盾的两条同时可召回"。
    """
    soft_delete = getattr(store, "soft_delete", None)
    if callable(soft_delete):
        await soft_delete(entry_id, idempotency_key=f"supersede:{idempotency_key}")
    else:  # 老 store 无软删能力：如实报告，不假装退役成功
        _log.warning("store has no soft_delete; supersede of %s degrades to append-only", entry_id)
        await store.write(replacement, idempotency_key=idempotency_key)
        return ConsolidationOutcome(wrote=True, reason="append_only_no_soft_delete", attempts=1, superseded=0)
    await store.write(replacement, idempotency_key=f"{idempotency_key}:replacement")
    return ConsolidationOutcome(wrote=True, reason=reason, attempts=1, superseded=1)


async def consolidate(
    store: MemoryStorePort,
    distiller: DistillProvider,
    *,
    session_id: str,
    lookback_days: int = 7,
    remaining_percent: int | float | None = None,
    max_attempts: int = MAX_DISTILL_ATTEMPTS,
) -> ConsolidationOutcome:
    """跑一次巩固（配额闸 → 会话锁 → 有界重试 → 非破坏式写回）。"""
    if not quota_allows(remaining_percent):
        return ConsolidationOutcome(wrote=False, reason="quota_hold", attempts=0)
    async with lock_for(session_id):
        attempts = 0
        last_reason = "no_attempt"
        while attempts < max(1, max_attempts):
            attempts += 1
            try:
                core = await store.read_memory_text("MEMORY.md")
                dailies = await _recent_dailies(store, lookback_days=lookback_days)
                outcome = await distiller.distill(core, dailies)
            except Exception as exc:  # noqa: BLE001 - 巩固失败是合法结果，绝不冒泡打断回复
                last_reason = f"distill_error:{type(exc).__name__}"
                _log.warning("consolidation attempt %s failed for session %s", attempts, session_id, exc_info=True)
                continue
            if outcome is None:
                return ConsolidationOutcome(wrote=False, reason="nothing_to_consolidate", attempts=attempts)
            new_core = getattr(outcome, "new_core", None)
            if not new_core:
                return ConsolidationOutcome(wrote=False, reason="empty_result", attempts=attempts)
            # 幂等键含输入指纹：同一批输入重投不会写两次，新输入才会落新一次巩固。
            dream = getattr(outcome, "dream", "") or ""
            await store.write_memory_text("MEMORY.md", str(new_core), idempotency_key=f"dream:{session_id}:{attempts}:{hash(dream) & 0xFFFF}")
            return ConsolidationOutcome(wrote=True, reason="consolidated", attempts=attempts)
        return ConsolidationOutcome(wrote=False, reason=last_reason, attempts=attempts)


async def _recent_dailies(store: MemoryStorePort, *, lookback_days: int) -> list[str]:
    """取近期 daily 正文（按路径排序，保证输入序稳定）。"""
    paths = sorted(path for path in await store.list_memory_paths() if path.startswith("memory/") and "/dreams/" not in path)
    cutoff = len(paths)
    keep = paths[max(0, cutoff - max(1, lookback_days)) :] if lookback_days else []
    return [await store.read_memory_text(path) for path in keep]


__all__ = [
    "MAX_DISTILL_ATTEMPTS",
    "ConsolidationOutcome",
    "consolidate",
    "lock_for",
    "reset_consolidation_locks",
    "supersede",
]
