"""SSE 字节层单测：格式逐字、心跳与 Last-Event-ID 解析。"""

from __future__ import annotations

from questorharness.bootstrap.hosts.serve import eventstream


def test_format_sse_bytes_are_exact() -> None:
    """格式是契约：id / event / data + 空行。"""
    payload = eventstream.format_sse(7, {"kind": "text", "text": "hi", "seq": 7})
    assert payload == b'id: 7\nevent: frame\ndata: {"kind":"text","text":"hi","seq":7}\n\n'


def test_heartbeat_carries_watermark() -> None:
    """空闲心跳携带水位。"""
    assert eventstream.heartbeat_bytes(9) == b'event: heartbeat\ndata: {"watermark":9}\n\n'


def test_last_event_id_parsing_is_strict() -> None:
    """非法值按未提供处理，不猜。"""
    assert eventstream.parse_last_event_id(None) is None
    assert eventstream.parse_last_event_id("") is None
    assert eventstream.parse_last_event_id("abc") is None
    assert eventstream.parse_last_event_id("-1") is None
    assert eventstream.parse_last_event_id(" 12 ") == 12


def test_dumps_keeps_unicode() -> None:
    """中文不转义，便于抓包与回放阅读。"""
    assert eventstream.dumps({"text": "你好"}) == '{"text":"你好"}'.encode()
