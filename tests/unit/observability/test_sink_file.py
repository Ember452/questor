"""T2.8 file sink ``observability/sink_file.py`` 判例（DESIGN §10；G-L9；tmp 真 IO）。

**不用 mock 冒充 IO**：全用 ``tmp_path`` 真实读写。覆盖 roundtrip、WARNING+ 分流 ``errors``、跨日
换文件、JSONL 单行（含异常链栈）、软阈值提级且 ``errors`` lane 不受影响、**提级不跨日泄漏**、保留期
懒清理、只读目录降级 console-only、llm 通道默认不写。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from questor.observability.entry import LogEntry, LogLevel
from questor.observability.sink_file import FileSink


def _entry(
    msg: str = "hello",
    level: LogLevel = LogLevel.INFO,
    logger: str = "questor.kernel.loop",
    traceback: str | None = None,
    ts: datetime | None = None,
) -> LogEntry:
    return LogEntry(
        ts=ts or datetime.now(UTC),
        level=level,
        logger=logger,
        msg=msg,
        fields={},
        traceback=traceback,
        source="inline",
        context={},
    )


def _read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_roundtrip_single_file(tmp_path: Path) -> None:
    sink = FileSink(tmp_path / "logs")
    sink.emit(_entry(msg="boot ok"))
    files = list((tmp_path / "logs").glob("questor-*.jsonl"))
    assert len(files) == 1
    recs = _read(files[0])
    assert recs[0]["msg"] == "boot ok"
    assert recs[0]["level"] == "INFO"
    assert recs[0]["source"] == "inline"


def test_errors_lane_for_warning_plus(tmp_path: Path) -> None:
    sink = FileSink(tmp_path / "logs")
    sink.emit(_entry(msg="danger", level=LogLevel.WARNING))
    date = datetime.now(UTC).strftime("%Y%m%d")
    main = _read(tmp_path / "logs" / f"questor-{date}.jsonl")
    errs = _read(tmp_path / "logs" / f"errors-{date}.jsonl")
    assert main[0]["msg"] == "danger"
    assert errs[0]["msg"] == "danger"  # WARNING+ 同时分流 errors


def test_cross_day_rotates_files(tmp_path: Path) -> None:
    sink = FileSink(tmp_path / "logs")
    day1 = datetime(2026, 1, 1, 12, tzinfo=UTC)
    day2 = datetime(2026, 1, 2, 12, tzinfo=UTC)
    sink.emit(_entry(msg="d1", ts=day1))
    sink.emit(_entry(msg="d2", ts=day2))
    assert (tmp_path / "logs" / "questor-20260101.jsonl").exists()
    assert (tmp_path / "logs" / "questor-20260102.jsonl").exists()


def test_traceback_stays_single_line(tmp_path: Path) -> None:
    sink = FileSink(tmp_path / "logs")
    tb = 'Traceback (most recent call last):\n  File "x.py", line 1\nValueError: boom'
    sink.emit(_entry(msg="failed", level=LogLevel.ERROR, traceback=tb))
    date = datetime.now(UTC).strftime("%Y%m%d")
    lines = (tmp_path / "logs" / f"errors-{date}.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1  # 含换行的 traceback 经 JSON 转义后仍是一物理行
    assert "boom" in json.loads(lines[0])["traceback"]  # 栈内容完整保留


def test_soft_threshold_raises_and_errors_lane_unaffected(tmp_path: Path) -> None:
    sink = FileSink(tmp_path / "logs", file_level=LogLevel.DEBUG, max_size_bytes=1)
    sink.emit(_entry(msg="first" * 50, level=LogLevel.DEBUG))  # 触发超阈值 → 提级 INFO
    assert sink.min_level == LogLevel.INFO  # §16.3 主动降级
    # 提级后再来 DEBUG：主干不再收录（低于新 min_level）。
    sink.emit(_entry(msg="debug-after-degrade", level=LogLevel.DEBUG))
    date = datetime.now(UTC).strftime("%Y%m%d")
    main_text = (tmp_path / "logs" / f"questor-{date}.jsonl").read_text(encoding="utf-8")
    assert "debug-after-degrade" not in main_text
    # errors lane（WARNING+）不受提级影响：ERROR 仍分流落盘。
    sink.emit(_entry(msg="err-after-degrade", level=LogLevel.ERROR))
    errs_text = (tmp_path / "logs" / f"errors-{date}.jsonl").read_text(encoding="utf-8")
    assert "err-after-degrade" in errs_text


def test_lazy_gc_removes_expired(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "questor-20200101.jsonl").write_text("{}", encoding="utf-8")  # 远古
    recent = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y%m%d")
    (logs / f"questor-{recent}.jsonl").write_text("{}", encoding="utf-8")
    sink = FileSink(logs, keep_days=14)
    removed = sink.gc(keep_days=14)
    assert "questor-20200101.jsonl" in removed
    assert not (logs / "questor-20200101.jsonl").exists()
    assert (logs / f"questor-{recent}.jsonl").exists()


def test_sink_recovers_after_transient_degrade(tmp_path: Path) -> None:
    """#162A：瞬时降级不再永久停写——退避到期后一次成功写即自愈。"""
    sink = FileSink(tmp_path / "logs")
    sink.degraded = True
    sink._degrade_streak = 1
    sink._retry_after = float("inf")  # 退避未到 → emit 抑制不写
    sink.emit(_entry(msg="suppressed"))
    date = datetime.now(UTC).strftime("%Y%m%d")
    main_text = (tmp_path / "logs" / f"questor-{date}.jsonl")
    assert not main_text.exists() or "suppressed" not in main_text.read_text(encoding="utf-8")
    # 退避到期（设 _retry_after=0）→ 下次 emit 写成功并从降级态恢复。
    sink._retry_after = 0.0
    sink.emit(_entry(msg="recovered"))
    assert sink.degraded is False
    assert "recovered" in main_text.read_text(encoding="utf-8")


def test_degraded_readonly_dir_no_crash(tmp_path: Path) -> None:
    blocker = tmp_path / "blocked"  # 用普通文件占位 → 其下无法建子目录
    blocker.write_text("x", encoding="utf-8")
    sink = FileSink(blocker / "logs")
    assert sink.degraded is True  # 目录不可建即降级
    sink.emit(_entry(msg="should not raise"))  # 绝不抛
    st = sink.status()
    assert st["degraded"] is True


def test_llm_channel_default_off(tmp_path: Path) -> None:
    sink = FileSink(tmp_path / "logs", llm_file=False)
    sink.emit(_entry(msg="llm meta", level=LogLevel.DEBUG, logger="questor.llm"))
    assert not list((tmp_path / "logs").glob("llm-*.jsonl"))  # 默认不写 llm 通道


def test_soft_threshold_raise_resets_on_new_day(tmp_path: Path) -> None:
    """#135：软阈值提级只能作用于触发那一天，换日必须回到调用方要求的门。

    旧实现是进程终身制（单计数器 + 单布尔永不复位）：一天写多之后，此后所有新分片永久丢 DEBUG——
    长跑 sidecar 上等于"第一晚很噪 → 以后再也看不到细粒度日志"，而且除了 ``logging_status``
    无处发现。
    """
    today = datetime.now(UTC)
    tomorrow = today + timedelta(days=1)
    sink = FileSink(tmp_path / "logs", file_level=LogLevel.DEBUG, max_size_bytes=400)
    for i in range(12):
        sink.emit(_entry(msg=f"filler-{i} " * 6, level=LogLevel.DEBUG, ts=today))
    assert sink.min_level is LogLevel.INFO, "当日越线应提级"

    sink.emit(_entry(msg="next-day-debug", level=LogLevel.DEBUG, ts=tomorrow))
    next_day_file = tmp_path / "logs" / f"questor-{tomorrow:%Y%m%d}.jsonl"
    assert next_day_file.exists(), "次日应开新分片"
    assert any(r["msg"] == "next-day-debug" for r in _read(next_day_file)), "次日必须回到 DEBUG 门"
    assert sink.min_level is LogLevel.DEBUG

    st = sink.status()
    assert st["base_file_level"] == "DEBUG" and st["raised_days"], "自我观测要能看出哪一天被降过级"
    assert st["written_bytes"] > 0


def test_llm_channel_enabled(tmp_path: Path) -> None:
    sink = FileSink(tmp_path / "logs", llm_file=True, file_level=LogLevel.DEBUG)
    sink.emit(_entry(msg="llm meta", level=LogLevel.INFO, logger="questor.llm"))
    assert list((tmp_path / "logs").glob("llm-*.jsonl"))  # 开启后承载 questor.llm 行
