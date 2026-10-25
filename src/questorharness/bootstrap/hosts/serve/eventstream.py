"""SSE 字节层：格式、心跳与 Last-Event-ID 解析。

字节在这里定型，内存 transport 与回环 TCP 共用同一个函数——否则阶段 3
才暴露的格式问题会被阶段 1 的"假绿"掩盖。
"""

from __future__ import annotations

import json
from typing import Any, Final

Frame = dict[str, Any]

_EVENT_FRAME: Final[str] = "frame"
_EVENT_HEARTBEAT: Final[str] = "heartbeat"


def dumps(frame: Frame) -> bytes:
    """紧凑 JSON，保留中文。"""
    return json.dumps(frame, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def format_sse(seq: int, frame: Frame) -> bytes:
    """拼一条标准 SSE 事件。"""
    head = b"id: " + str(seq).encode("ascii") + b"\nevent: " + _EVENT_FRAME.encode("ascii")
    return head + b"\ndata: " + dumps(frame) + b"\n\n"


def heartbeat_bytes(seq: int) -> bytes:
    """空闲心跳帧；携带 watermark 供客户端判断落后程度。"""
    payload = dumps({"watermark": seq})
    return b"event: " + _EVENT_HEARTBEAT.encode("ascii") + b"\ndata: " + payload + b"\n\n"


def parse_last_event_id(raw: str | None) -> int | None:
    """解析 Last-Event-ID；非法值按"未提供"处理（不猜）。"""
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None
