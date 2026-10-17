"""P7 T2：bus 级只读带外投影——emit 对每条对外 Envelope **恰触发一次** observer（D-P7-A）。

判红目标（先于实现）：
- `InProcessEventBus` 暴露 `add_observer`，`emit` 对每条**投影后**的 Envelope 调用一次 observer，
  与订阅者数量无关（多挂订阅者**不增份**）；`INTERNAL_ONLY` 不外发 → observer 不触发。
- 组合根/surfaces（serve + CLI）在 bus 上挂**一条** `log_envelope` observer；`cli._stream` 的逐消费者
  `log_envelope` 必须**删除**（否则多 surface 双投，违 C6 折叠/合并同罪、C20 第二载体、pitfalls#2）。
"""

from __future__ import annotations

import inspect

from questor.contracts.events import Envelope, EventType
from questor.kernel.events import InProcessEventBus
from questor.surfaces import cli


async def test_emit_invokes_observer_once_per_projected_envelope_regardless_of_subscribers() -> None:
    """核心不变式：observer 触发次数 == 对外事件数，与挂了多少订阅者无关。"""
    bus = InProcessEventBus(None)
    seen: list[str] = []
    bus.add_observer(lambda env: seen.append(env.type))

    # 挂 3 个消费者订阅队列（模拟桌面 SSE + CLI + 再来一个），但**不排空**它们。
    for _ in range(3):
        bus.add_subscriber("run_x")

    await bus.emit(Envelope(v=1, seq=1, run_id="run_x", type=EventType.RUN_STARTED, data={"run_id": "run_x"}))
    await bus.emit(Envelope(v=1, seq=2, run_id="run_x", type=EventType.TEXT_DELTA, data={"delta": "hi", "item_id": None}))
    # 内部私有事件：投影时被滤掉，不外发 → observer 也不该收到。
    await bus.emit(Envelope(v=1, seq=3, run_id="run_x", type="checkpoint_recorded", data={"checkpoint": {}}))

    assert seen == [EventType.RUN_STARTED, EventType.TEXT_DELTA], seen  # 恰一次/条，内部排除，非 3×

    # 再挂一个订阅者后继续 emit：observer 仍只 +1（不随订阅者数量增长）。
    bus.add_subscriber("run_x")
    await bus.emit(Envelope(v=1, seq=4, run_id="run_x", type=EventType.RUN_COMPLETED, data={"usage": {}, "exit_reason": "answered"}))
    assert seen == [EventType.RUN_STARTED, EventType.TEXT_DELTA, EventType.RUN_COMPLETED], seen


def test_cli_stream_no_longer_calls_log_envelope() -> None:
    """逐消费者 ``log_envelope(...)`` 调用已删（回归栅栏）：若有人把它塞回 `_stream`，本用例判红。

    只断言**调用**形式（`log_envelope(`），不拦文档字符串里对它的提及（那里在解释为何删除）。"""
    src = inspect.getsource(cli.CliSurface._stream)
    assert "log_envelope(" not in src, "cli._stream 不应再逐消费者调 log_envelope（改由 bus 级订阅，ADR-0033）"
