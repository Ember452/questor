"""T2.6 治理管线 ``observability/pipeline.py`` 判例（DESIGN §0/§10/§13；D12/D13）。

覆盖管线次序 **脱敏 → 节流 → 级别 → fan-out**：redact-before-fanout、同签名 1s 窗合并且窗尾补
``repeated N times``、按每 sink 的 ``min_level`` 过滤（§16.3 降级读可变态）、**exporter 异常绝不上冒**
（计数 + 一次性自我禁用 + stderr 一行）。时钟用 monkeypatch 固定，测确定性。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from questor.observability import pipeline
from questor.observability.entry import LogEntry, LogLevel
from questor.observability.exporter import register

_SECRET = "sk-abcdef1234567890WXYZ"


def _entry(msg: str, level: LogLevel = LogLevel.INFO) -> LogEntry:
    return LogEntry(ts=datetime.now(UTC), level=level, logger="questor.t", msg=msg, source="inline")


class _Sink:
    def __init__(self, name: str = "sink", min_level: LogLevel | None = None) -> None:
        self.name = name
        self.got: list[LogEntry] = []
        if min_level is not None:
            self.min_level = min_level  # 有则 pipeline 按它过滤

    def emit(self, entry: LogEntry) -> None:
        self.got.append(entry)


class _Boom(_Sink):
    def emit(self, entry: LogEntry) -> None:
        raise RuntimeError("sink exploded")


@pytest.fixture
def add(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    pipeline.reset()
    made: list = []

    def _add(sink: _Sink) -> _Sink:
        made.append(register(sink))
        return sink

    yield _add
    for unreg in made:
        unreg()
    pipeline.reset()


def test_redact_happens_before_fanout(add) -> None:  # noqa: ANN001
    sink = add(_Sink())
    pipeline.emit(_entry(f"using {_SECRET}"))
    assert _SECRET not in sink.got[0].msg
    assert sink.got[0].fields.get("redacted") is True


def test_throttle_merges_and_emits_repeated_at_window_end(add, monkeypatch: pytest.MonkeyPatch) -> None:
    t = {"v": 0.0}
    monkeypatch.setattr(pipeline, "_clock", lambda: t["v"])
    sink = add(_Sink())
    for _ in range(3):
        pipeline.emit(_entry("spam"))  # 同签名，窗口内
    assert len(sink.got) == 1  # 首次立即放行，后两次抑制
    t["v"] = pipeline._WINDOW_SECONDS + 0.5
    pipeline.flush()
    assert len(sink.got) == 2  # 窗尾补一条 summary
    assert sink.got[1].fields.get("repeated") == 2  # 抑制了 2 条


def test_level_gate_per_sink_skips_below_min(add) -> None:  # noqa: ANN001
    sink = add(_Sink(min_level=LogLevel.ERROR))
    pipeline.emit(_entry("info line", level=LogLevel.INFO))
    assert sink.got == []
    pipeline.emit(_entry("err line", level=LogLevel.ERROR))
    assert [e.msg for e in sink.got] == ["err line"]


def test_exporter_exception_self_disables_and_never_propagates(add) -> None:  # noqa: ANN001
    boom = add(_Boom(name="boom"))
    ok = add(_Sink(name="ok"))
    pipeline.emit(_entry("a"))  # boom 抛 → 自我禁用 + 计数 + stderr 一行；不上冒
    assert len(ok.got) == 1
    pipeline.emit(_entry("b"))  # boom 已禁用，跳过；ok 继续
    assert len(ok.got) == 2
    st = pipeline.stats()
    assert "boom" in st["disabled_exporters"]
    assert st["dropped_records"] >= 2  # e1 抛错 + e2 跳过各计一次
    assert boom not in _live_current()  # 已不在活跃处理路径（靠 _disabled 跳过）


def _live_current() -> list:
    from questor.observability.exporter import current_exporters

    return [e for e in current_exporters() if not any(e is d for d in pipeline._disabled)]
