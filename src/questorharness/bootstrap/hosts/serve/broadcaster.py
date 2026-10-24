"""帧广播：单调 seq、可丢分类、8MB 有界重放。

seq 由本模块分配（wire.py 只产出不带 seq 的帧），这样重放窗口的判定
与编码细节无关。
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Final

Frame = dict[str, Any]

DROPPABLE_KINDS: Final[frozenset[str]] = frozenset({"compaction_progress"})
_MAX_QUEUE: Final[int] = 256


def is_droppable(frame: Frame) -> bool:
    """进度类可丢、事实类不可丢。"""
    if frame.get("kind") in DROPPABLE_KINDS:
        return True
    return frame.get("kind") == "notice" and frame.get("level") == "info"


def frame_size(frame: Frame) -> int:
    """按 JSON 字节数计量重放窗口，避免"帧数"掩盖大帧。"""
    return len(json.dumps(frame, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


@dataclass
class Subscriber:
    """一个 SSE 订阅者。"""

    queue: asyncio.Queue[tuple[int, Frame] | None] = field(
        default_factory=lambda: asyncio.Queue(maxsize=_MAX_QUEUE)
    )
    overflowed: bool = False
    dropped: int = 0


@dataclass(frozen=True)
class Replay:
    """重放结果；gap=True 表示窗口已越过请求点。"""

    frames: tuple[tuple[int, Frame], ...]
    gap: bool


class Broadcaster:
    """持有重放窗口与全部订阅者。"""

    def __init__(self, *, max_bytes: int = 8 * 1024 * 1024) -> None:
        self._max_bytes = max_bytes
        self._history: deque[tuple[int, Frame]] = deque()
        self._bytes = 0
        self._seq = 0
        self._subscribers: list[Subscriber] = []
        self.dropped_total = 0

    @property
    def watermark(self) -> int:
        """当前最大 seq；心跳帧带它作为水位。"""
        return self._seq

    @property
    def oldest(self) -> int | None:
        """重放窗口内最旧的 seq。"""
        return self._history[0][0] if self._history else None

    async def publish(self, frame: Frame) -> int:
        """分配 seq、入窗、扇出；返回新 seq。"""
        self._seq += 1
        seq = self._seq
        payload = {**frame, "seq": seq}
        self._remember(seq, payload)
        for subscriber in list(self._subscribers):
            self._offer(subscriber, seq, payload)
        return seq

    def _remember(self, seq: int, frame: Frame) -> None:
        """按字节上限裁剪最旧帧。"""
        self._history.append((seq, frame))
        self._bytes += frame_size(frame)
        while self._bytes > self._max_bytes and len(self._history) > 1:
            _, dropped_frame = self._history.popleft()
            self._bytes -= frame_size(dropped_frame)

    def _offer(self, subscriber: Subscriber, seq: int, frame: Frame) -> None:
        """投递给单个订阅者；满队列时丢可丢帧，事实帧挤掉最旧。"""
        item: tuple[int, Frame] = (seq, frame)
        try:
            subscriber.queue.put_nowait(item)
            return
        except asyncio.QueueFull:
            pass
        if is_droppable(frame):
            subscriber.dropped += 1
            self.dropped_total += 1
            return
        subscriber.overflowed = True
        try:
            subscriber.queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        subscriber.queue.put_nowait(item)

    def subscribe(self) -> Subscriber:
        """新增一个只收新帧的订阅者（attach ≠ resume）。"""
        subscriber = Subscriber()
        self._subscribers.append(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: Subscriber) -> None:
        """移除订阅者（幂等）。"""
        if subscriber in self._subscribers:
            self._subscribers.remove(subscriber)

    def replay(self, last_event_id: int | None) -> Replay:
        """计算断线重放；窗口不足时返回 gap。"""
        if last_event_id is None:
            return Replay(frames=(), gap=False)
        if last_event_id > self._seq:
            return Replay(frames=(), gap=True)
        oldest = self.oldest
        if oldest is not None and last_event_id + 1 < oldest:
            return Replay(frames=(), gap=True)
        frames = tuple((seq, frame) for seq, frame in self._history if seq > last_event_id)
        return Replay(frames=frames, gap=False)
