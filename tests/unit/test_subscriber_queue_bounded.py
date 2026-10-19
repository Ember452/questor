"""#174：事件总线订阅队列有界（激活既定 QueueFull 丢帧→resync 背压，钉死慢消费者无界堆积）。"""

from __future__ import annotations

from questor.kernel.events import InProcessEventBus


def test_subscriber_queue_is_bounded() -> None:
    bus = InProcessEventBus()
    queue = bus.add_subscriber("run_x")
    assert queue.maxsize > 0, "订阅队列仍无界 → QueueFull 丢帧/背压路径为死代码（#174）"
