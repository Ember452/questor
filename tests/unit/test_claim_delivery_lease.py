"""P9 T8：claim/delivery_state 账本 + 单机 run 租约（SQLiteStore，ADR-0047）。

真依赖判据：claim/delivery 方法存在 ≠ 崩溃一致性——本测钉 ①同投递 id 二次 claim=no-op、
ack 幂等、②claim 超 TTL 可重取（崩溃恢复、不永久丢投）、③租约同 holder 可续/异 holder 被拒、
释放后可再取。跨进程真双驱见 integration/test_run_lease_multiprocess.py。
"""

from __future__ import annotations

import asyncio

from questor.providers.store_sqlite import SQLiteStore


def test_claim_and_ack_idempotent() -> None:
    async def _go() -> None:
        store = await SQLiteStore(":memory:").connect()
        try:
            assert await store.claim_delivery("d1", ttl_seconds=100) is True
            assert await store.claim_delivery("d1", ttl_seconds=100) is False  # 他人持有未过期
            assert await store.delivery_state("d1") == "claimed"
            assert await store.ack_delivery("d1") is True
            assert await store.delivery_state("d1") == "acked"
            assert await store.ack_delivery("d1") is True  # 幂等
            assert await store.claim_delivery("d1", ttl_seconds=100) is False  # 已 acked 不再投
        finally:
            await store.close()

    asyncio.run(_go())


def test_claim_expires_allows_crash_reacquire() -> None:
    async def _go() -> None:
        store = await SQLiteStore(":memory:").connect()
        try:
            assert await store.claim_delivery("d2", ttl_seconds=0.0) is True
            await asyncio.sleep(0.02)  # 前次 claim 立即过期（模拟持有者崩溃）
            assert await store.claim_delivery("d2", ttl_seconds=100) is True  # 可重取，不永久丢投
        finally:
            await store.close()

    asyncio.run(_go())


def test_ack_unknown_is_false() -> None:
    async def _go() -> None:
        store = await SQLiteStore(":memory:").connect()
        try:
            assert await store.ack_delivery("nope") is False  # 从未 claim，不能凭空 ack
        finally:
            await store.close()

    asyncio.run(_go())


def test_run_lease_single_writer_renew_release() -> None:
    async def _go() -> None:
        store = await SQLiteStore(":memory:").connect()
        try:
            assert await store.acquire_lease("r1", "A", 1, ttl_seconds=100) is True
            assert await store.acquire_lease("r1", "B", 1, ttl_seconds=100) is False  # A 未过期持有
            assert await store.renew_lease("r1", "B", 1) is False  # 非 holder 不能续
            assert await store.renew_lease("r1", "A", 1) is True
            assert await store.release_lease("r1", "B", 1) is False  # 非 holder 不能释放
            assert await store.release_lease("r1", "A", 1) is True
            assert await store.acquire_lease("r1", "B", 2, ttl_seconds=100) is True  # 释放后 B 可取
        finally:
            await store.close()

    asyncio.run(_go())
