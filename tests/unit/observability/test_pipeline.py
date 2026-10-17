"""T2.6 治理管线 ``observability/pipeline.py`` 判例（DESIGN §0/§10/§13；D12/D13）。

覆盖管线次序 **脱敏 → 节流 → 来源/级别门 → fan-out**：redact-before-fanout、同签名 1s 窗合并且窗尾补
``repeated N times``、按每 sink 的 ``min_level`` + 来源门过滤（§16.3 降级读可变态）、**exporter 异常绝不上冒**
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


# ---------------------------------------------------------------------------
# 缺陷审计补的判据（Issue #126/#128/#131/#132）：下面每条在修复前均实测为红。
# ---------------------------------------------------------------------------


def _entry_of(logger: str, level: LogLevel, msg: str, *, context: dict | None = None, fields: dict | None = None) -> LogEntry:
    return LogEntry(
        ts=datetime.now(UTC), level=level, logger=logger, msg=msg, source="inline",
        context=context or {}, fields=fields or {},
    )


def test_third_party_debug_never_fans_out_even_behind_a_debug_gate(add) -> None:  # noqa: ANN001
    """#126 来源门：非 ``questor.*`` 的 DEBUG 不得进任何 sink，哪怕该 sink 的门开到 DEBUG。

    为什么重要：主干 ``file_level=DEBUG`` 本是给一方记录准备的，但它一并把 aiosqlite 的
    "executing <SQL> <参数元组>" 灌进日志文件——参数元组里就是 prompt 与 checkpoint 原文。
    """
    sink = add(_Sink(min_level=LogLevel.DEBUG))
    pipeline.emit(_entry_of("aiosqlite", LogLevel.DEBUG, "executing INSERT INTO checkpoints ... ('cp1', 'run1', '{\"text\":\"prompt\"}')"))
    assert sink.got == [], "外来 DEBUG 不得穿透来源门"

    pipeline.emit(_entry_of("aiosqlite", LogLevel.INFO, "connection opened"))
    assert [e.msg for e in sink.got] == ["connection opened"], "外来 INFO+ 仍放行（降噪不靠丢级别）"

    pipeline.emit(_entry_of("questor.store", LogLevel.DEBUG, "first-party debug passes"))
    assert any(e.logger == "questor.store" for e in sink.got), "一方 DEBUG 必须照旧能进"


def test_error_entries_bypass_throttle_across_runs(add, monkeypatch: pytest.MonkeyPatch) -> None:
    """#128：两个 run 同秒各失败一次——两条 ERROR 都必须留下，且不许出现 ``repeated``。

    判红样例：把签名里的 ``run_id`` 拿掉并让 ERROR 走节流窗，本测试即红（后一个 run 消失）。
    """
    t = {"v": 0.0}
    monkeypatch.setattr(pipeline, "_clock", lambda: t["v"])
    sink = add(_Sink())
    for rid, why in (("RUN-A", "401 key expired"), ("RUN-B", "500 upstream")):
        pipeline.emit(
            _entry_of(
                "questor.events.run_failed",
                LogLevel.ERROR,
                "event run_failed",
                context={"run_id": rid},
                fields={"error_message": why},
            )
        )
    assert len(sink.got) == 2, "ERROR 不得被节流合并"
    assert {e.context["run_id"] for e in sink.got} == {"RUN-A", "RUN-B"}
    assert all("repeated" not in e.fields for e in sink.got)


def test_throttle_merges_same_shape_different_numbers(add, monkeypatch: pytest.MonkeyPatch) -> None:
    """#131：指纹用形状而不是整条 msg——"同一行代码、值不同"必须被合并。"""
    t = {"v": 0.0}
    monkeypatch.setattr(pipeline, "_clock", lambda: t["v"])
    sink = add(_Sink())
    for i in range(5):
        pipeline.emit(_entry(f"retry in {i}s", LogLevel.INFO))
    assert len(sink.got) == 1, f"同形状应只放行首条，实际 {len(sink.got)}"
    t["v"] = pipeline._WINDOW_SECONDS + 0.5
    pipeline.flush()
    assert sink.got[-1].fields.get("repeated") == 4


def test_emit_swallows_pipeline_internal_errors(add, monkeypatch: pytest.MonkeyPatch) -> None:
    """#132：“绝不上冒”必须覆盖管线自身，不只是 exporter 调用那一段。"""
    sink = add(_Sink())

    def boom(_entry: LogEntry) -> None:
        raise ValueError("internal pipeline fault")

    monkeypatch.setattr(pipeline, "_emit_guarded", boom)
    pipeline.emit(_entry("would raise"))  # 不得抛
    assert sink.got == []
    assert pipeline.stats()["dropped_records"] >= 1


def test_flush_survives_marker_key_clash_with_context(add, monkeypatch: pytest.MonkeyPatch) -> None:
    """#132：窗尾补行往 fields 注入 ``repeated``，若 ``context`` 已有同名键不得抛 ValueError。

    不变式 5（fields ∩ context 必须不相交）在 ``dataclasses.replace`` 重跑 ``__post_init__`` 时会炸；
    炸在 ``flush()`` 里就是“为了写日志把宿主打穿”。
    """
    t = {"v": 0.0}
    monkeypatch.setattr(pipeline, "_clock", lambda: t["v"])
    sink = add(_Sink())
    clash = LogEntry(
        ts=datetime.now(UTC), level=LogLevel.INFO, logger="questor.t", msg="dup", source="inline",
        context={"repeated": 9},
    )
    pipeline.emit(clash)
    pipeline.emit(clash)  # 进同一窗 → 窗尾要补 repeated
    t["v"] = pipeline._WINDOW_SECONDS + 0.5
    pipeline.flush()  # 不得抛
    assert len(sink.got) >= 1
