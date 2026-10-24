"""广播器单测：seq、可丢分级、有界重放与越界 gap。"""

from __future__ import annotations

import asyncio

from questorharness.bootstrap.hosts.serve.broadcaster import Broadcaster, is_droppable


def test_sequence_is_monotonic_across_publishes() -> None:
    """seq 只由 broadcaster 分配，且单调递增。"""

    async def scenario() -> None:
        relay = Broadcaster()
        first = await relay.publish({"kind": "text", "text": "a"})
        second = await relay.publish({"kind": "text", "text": "b"})
        assert (first, second) == (1, 2)
        assert relay.watermark == 2

    asyncio.run(scenario())


def test_droppable_classification() -> None:
    """进度与 info 可丢；事实帧不可丢。"""
    assert is_droppable({"kind": "compaction_progress"})
    assert is_droppable({"kind": "notice", "level": "info"})
    assert not is_droppable({"kind": "text"})
    assert not is_droppable({"kind": "notice", "level": "error"})
    assert not is_droppable({"kind": "turn_done"})


def test_replay_returns_frames_after_cursor() -> None:
    """断点之后补帧。"""

    async def scenario() -> None:
        relay = Broadcaster()
        for index in range(5):
            await relay.publish({"kind": "text", "text": str(index)})
        replay = relay.replay(2)
        assert [seq for seq, _ in replay.frames] == [3, 4, 5]
        assert replay.gap is False
        assert relay.replay(None).frames == ()

    asyncio.run(scenario())


def test_replay_gap_when_window_is_too_small() -> None:
    """窗口越过请求点必须报 gap，而不是假装连续。"""

    async def scenario() -> None:
        relay = Broadcaster(max_bytes=120)
        for index in range(20):
            await relay.publish({"kind": "text", "text": f"frame-{index}"})
        assert relay.oldest is not None
        replay = relay.replay(1)
        assert replay.gap is True
        assert replay.frames == ()

    asyncio.run(scenario())


def test_slow_subscriber_drops_droppable_frames() -> None:
    """慢消费者只丢可丢帧；事实帧挤掉最旧并标记 overflow。"""

    async def scenario() -> None:
        relay = Broadcaster()
        subscriber = relay.subscribe()
        for index in range(300):
            await relay.publish({"kind": "compaction_progress", "phase": "compact_start"})
        assert subscriber.dropped > 0
        await relay.publish({"kind": "text", "text": "fact"})
        assert subscriber.overflowed is True

    asyncio.run(scenario())
