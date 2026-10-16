"""T2.11 带外投影 ``observability/projection.py`` 判例（DESIGN §7/§9；G-L11/C6/C5）。

投影是**唯一允许 import questor.contracts 的文件**。覆盖：级别映射（错误类绝不静默 C6、里程碑
INFO、余 DEBUG）、live-only 丢弃集（含补齐的 usage_delta/node_updated）、载荷只取白名单键
（G-L11）、``source="event"``、经 pipeline 汇流。
"""

from __future__ import annotations

from datetime import UTC, datetime

from questor.contracts.events import Envelope, EventType
from questor.observability import pipeline
from questor.observability.entry import LogEntry, LogLevel
from questor.observability.exporter import register
from questor.observability.projection import log_envelope, project


def _env(type_: str, data: dict | None = None, turn: int | None = 1, seq: int = 7) -> Envelope:
    return Envelope(
        v=1,
        seq=seq,
        run_id="r1",
        type=type_,
        turn=turn,
        ts=datetime(2026, 1, 1, tzinfo=UTC),
        data=data or {},
    )


class _Sink:
    def __init__(self) -> None:
        self.got: list[LogEntry] = []

    def emit(self, entry: LogEntry) -> None:
        self.got.append(entry)


def _fresh_sink():  # noqa: ANN202
    pipeline.reset()
    sink = _Sink()
    return sink, register(sink)


def test_run_started_is_info_event() -> None:
    e = project(_env(EventType.RUN_STARTED))
    assert e is not None
    assert e.level is LogLevel.INFO
    assert e.source == "event"
    assert e.context["run_id"] == "r1"
    assert e.fields["seq"] == 7


def test_run_failed_is_error_and_carries_error_fields() -> None:
    e = project(_env(EventType.RUN_FAILED, {"error": {"code": "provider_4xx", "message": "bad"}}))
    assert e is not None
    assert e.level is LogLevel.ERROR  # C6：错误类绝不静默
    assert e.fields["error_code"] == "provider_4xx"
    assert e.fields["error_message"] == "bad"


def test_warning_and_resync_are_warning() -> None:
    assert project(_env(EventType.WARNING)).level is LogLevel.WARNING
    assert project(_env(EventType.RESYNC_REQUIRED)).level is LogLevel.WARNING


def test_other_events_are_debug() -> None:
    assert project(_env(EventType.TOOL_COMPLETED)).level is LogLevel.DEBUG


def test_live_only_events_dropped() -> None:
    for t in (
        EventType.TEXT_DELTA,
        EventType.REASONING_DELTA,
        EventType.TOOL_PROGRESS,
        EventType.HEARTBEAT,
        EventType.USAGE_DELTA,
        EventType.NODE_UPDATED,
    ):
        assert project(_env(t)) is None, f"{t} must be dropped"


def test_payload_only_whitelisted_keys() -> None:
    # G-L11：白名单外的键（如 prompt/result）绝不进载荷。
    e = project(_env(EventType.RUN_COMPLETED, {"status": "completed", "prompt": "SECRET", "result": {"big": 1}}))
    assert e is not None
    assert e.fields.get("status") == "completed"
    assert "prompt" not in e.fields
    assert "result" not in e.fields


def test_log_envelope_feeds_pipeline() -> None:
    sink, unreg = _fresh_sink()
    try:
        log_envelope(_env(EventType.RUN_STARTED))
        log_envelope(_env(EventType.TEXT_DELTA))  # 被丢弃 → 不进 sink
        assert len(sink.got) == 1
        assert sink.got[0].source == "event"
    finally:
        unreg()
        pipeline.reset()


def test_turn_none_stays_out_of_context() -> None:
    e = project(_env(EventType.RUN_STARTED, turn=None))
    assert e is not None
    assert "turn" not in e.context
