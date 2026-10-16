"""T2.7 console sink ``observability/sink_console.py`` 判例（DESIGN §10；G-L10）。

覆盖：渲染到指定流含级别名/logger/msg；**永不写 stdout**（默认落 stderr，G-L10 判红样例）；
非 UTF-8/编码异常不崩进程（降级为 ASCII ``replace`` 重写）。
"""

from __future__ import annotations

import io
from datetime import UTC, datetime

from questor.observability.entry import LogEntry, LogLevel
from questor.observability.sink_console import ConsoleSink


def _entry(msg: str = "boot ok", level: LogLevel = LogLevel.INFO) -> LogEntry:
    return LogEntry(
        ts=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        level=level,
        logger="questor.kernel.loop",
        msg=msg,
        source="inline",
        context={"run_id": "r1", "turn": 2},
    )


def test_renders_to_given_stream() -> None:
    buf = io.StringIO()
    ConsoleSink(stream=buf).emit(_entry())
    out = buf.getvalue()
    assert "INFO" in out
    assert "questor.kernel.loop" in out
    assert "boot ok" in out
    assert "run_id=r1" in out  # 关联键渲染进人读行


def test_never_writes_stdout(capsys) -> None:  # noqa: ANN001
    # G-L10：默认流 = stderr；机器可读的 stdout 保持洁净。把 sink 指 stdout 即会红此测。
    ConsoleSink().emit(_entry("hello-clean-stdout"))
    cap = capsys.readouterr()
    assert "hello-clean-stdout" not in cap.out
    assert "hello-clean-stdout" in cap.err


def test_unicode_error_falls_back_no_crash() -> None:
    class _Raising(io.TextIOBase):
        def __init__(self) -> None:
            self.writes: list[str] = []

        def write(self, s: str) -> int:
            # 首次按真实 stderr 在非 UTF-8 locale 下对某些字符抛 UnicodeEncodeError。
            if "\ud800" in s or "你好" in s:
                raise UnicodeEncodeError("ascii", s, 0, 1, "codec can't encode")
            self.writes.append(s)
            return len(s)

        def flush(self) -> None:
            pass

    stream = _Raising()
    sink = ConsoleSink(stream=stream)
    # 不应抛出到调用方（pipeline 也已兜 exporter 异常，这里验 sink 自身降级）。
    sink.emit(_entry("你好 \ud800"))
    assert stream.writes, "fallback must have written an ASCII-safe line"
    assert "boot" not in stream.writes[0]  # 仅确保写了降级行（非空）


def test_min_level_default_info() -> None:
    # console 默认 INFO（D10）；pipeline 按此属性过滤。
    assert ConsoleSink().min_level == LogLevel.INFO
