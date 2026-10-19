"""地基不变式：``InProcessEventBus.subscribe`` 必须回收自己的订阅队列（长驻 sidecar 不泄漏）。

真问题（审计 surfaces MAJ-1/MAJ-3/track4 MAJ-5）：``subscribe`` 先 ``add_subscriber`` 挂一个
``asyncio.Queue`` 进 ``self._subs[run_id]``，但**无 try/finally 摘除**——只有当某协程 ``emit`` 终态
事件时才 ``_subs.pop(run_id)`` 整体清。于是：
- 重放路径走到终态 ``return``（订阅者没在终态前挂上、终态已入库）→ 队列残留；
- 客户端断连（生成器被 ``aclose``/取消）→ 队列残留。
每次"重连到已终态 run""断连"都漏一个队列，常驻 sidecar 内存单调递增。这里证伪：订阅迭代结束/关闭后，
``_subs`` 必须回收该队列。
"""

from __future__ import annotations

import pytest

from questor.contracts.common import new_id
from questor.contracts.events import Envelope, EventType
from questor.kernel.events import InProcessEventBus
from questor.providers.store_sqlite import SQLiteStore


def _env(run_id: str, seq: int, etype: str) -> Envelope:
    from datetime import UTC, datetime

    return Envelope(v=1, seq=seq, run_id=run_id, type=etype, turn=0, data={}, ts=datetime.now(UTC))


@pytest.fixture
async def bus_store():
    store = await SQLiteStore(":memory:").connect()
    yield InProcessEventBus(store), store
    await store.close()


async def test_replay_terminal_return_cleans_subscriber(bus_store) -> None:
    """重放走到终态即 return：结束后不得在 _subs 里留下队列。"""
    bus, store = bus_store
    run_id = new_id("run")
    await bus.emit(_env(run_id, 1, EventType.RUN_STARTED))
    await bus.emit(_env(run_id, 2, EventType.RUN_COMPLETED))  # 终态先入库，此时无人订阅

    got = [e.type async for e in bus.subscribe(run_id, after_seq=0)]
    assert got == ["run_started", "run_completed"]
    subs = bus._subs.get(run_id, [])
    assert subs == [], f"重放到终态后队列未回收，泄漏 {len(subs)} 个订阅队列"


async def test_subscriber_close_cleans_queue(bus_store) -> None:
    """客户端提前断连（aclose 生成器）：队列必须被摘除。"""
    bus, store = bus_store
    run_id = new_id("run")
    await bus.emit(_env(run_id, 1, EventType.RUN_STARTED))  # 非终态，订阅会进入 live-follow 循环

    gen = bus.subscribe(run_id, after_seq=0)
    first = await gen.__anext__()  # 重放 run_started，随后进入 live-follow（挂上 queue）
    assert first.type == "run_started"
    await gen.aclose()  # 模拟断连：提前关闭生成器
    subs = bus._subs.get(run_id, [])
    assert subs == [], f"断连后队列未回收，泄漏 {len(subs)} 个"
