"""地基不变式：StorePort 在单连接上必须串行化事务（C2 单写者的持久化侧）。

真问题（审计 track4 BLK-1，探针实证）：``SQLiteStore`` 用一个 ``aiosqlite.Connection`` 承载
``BEGIN IMMEDIATE``→SELECT→INSERT→commit 的多条 ``await``，**无 asyncio.Lock**。两个并发协程
（如 HTTP 服务同时驱动两个 run / 父子协作 run）在同一连接上交错：第二个 ``BEGIN`` 落入对方事务
报 "cannot start a transaction within a transaction"，其 ``except`` 的 ROLLBACK 又撕掉第一个协程的
事务 → ``store.append`` 抛穿 ``bus.emit`` → run 无终态、账本半写。

桌面/serve 的多会话与 P8 父子协作是出厂路径，故并发落库必须串行。这里用真 store 证伪：并发 append
不得抛，且每个 run 的 seq 连续无缺。
"""

from __future__ import annotations

import asyncio

import pytest

from questor.providers.store_sqlite import SQLiteStore


@pytest.fixture
async def store():
    s = await SQLiteStore(":memory:").connect()
    yield s
    await s.close()


def _batch(prefix: str, n: int) -> tuple[dict, ...]:
    return tuple({"type": f"t_{prefix}_{i}", "data": {"i": i}} for i in range(n))


async def test_concurrent_appends_across_runs_are_serialized(store) -> None:
    """并发向两个 run 各追加 20 条事件：不得因事务交错而抛，seq 必须 1..20 连续且唯一。"""
    await asyncio.gather(
        *(store.append(f"run_{r}", _batch(f"r{r}", 20)) for r in range(4)),
    )
    for r in range(4):
        rows = await store.replay(f"run_{r}", after_seq=0)
        seqs = [row["seq"] for row in rows]
        assert seqs == list(range(1, 21)), f"run_{r} 落库 seq 缺失/错乱（事务互踩）：{seqs}"


async def test_concurrent_appends_same_run_take_distinct_seqs(store) -> None:
    """并发向同一 run 追加：每条仍必须各占唯一 seq（无重复、无覆盖丢失）。"""
    await asyncio.gather(*(store.append("run_x", _batch(f"c{c}", 5)) for c in range(4)))
    rows = await store.replay("run_x", after_seq=0)
    seqs = sorted(row["seq"] for row in rows)
    assert seqs == list(range(1, 21)), f"同 run 并发追加 seq 应 1..20 唯一连续：{seqs}"
