"""T2.9 stdlib 桥 ``observability/bridge.py`` 判例（DESIGN §6；G-L6/G-L12/§16.1）。

把 ``BridgeHandler`` 装到 root、注册一个管线 sink，经 ``logging.getLogger(...)`` 真实调用验证：
调用点保真（``filename`` 指业务文件非 ``bridge.py``，G-L6）、带内 args 非标量强转（§16.1）、
非 ``questor.*`` 不强转、``extra={"log_fields"}`` 唯一入口、traceback 压空行且栈完整（G-L12）、
``context`` 取自 ``bind()``、降噪白名单生效。
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest

from questor.observability import pipeline
from questor.observability.bridge import BridgeHandler, quiet_noisy_loggers
from questor.observability.entry import LogEntry
from questor.observability.exporter import register


class _Sink:
    def __init__(self) -> None:
        self.got: list[LogEntry] = []

    def emit(self, entry: LogEntry) -> None:
        self.got.append(entry)


@pytest.fixture
def harness() -> Iterator[_Sink]:
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    pipeline.reset()
    sink = _Sink()
    unreg = register(sink)
    handler = BridgeHandler()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        yield sink
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
        unreg()
        pipeline.reset()


class _RunLike:
    def __repr__(self) -> str:
        return "<Run run_id=abc>"


class _Leaky:
    def __repr__(self) -> str:
        return "repr sk-abcdef1234567890WXYZ end"


def test_call_site_is_business_file_not_bridge(harness: _Sink) -> None:
    # G-L6：filename 指真实调用处（本测试文件），不是 bridge.py。
    logging.getLogger("questor.demo").info("g6 probe")
    e = harness.got[-1]
    assert e.fields["filename"] == "test_bridge.py"
    assert e.fields["filename"] != "bridge.py"
    assert isinstance(e.fields["lineno"], int)


def test_non_scalar_arg_coerced(harness: _Sink) -> None:
    # §16.1：questor.* logger 的非白名单标量 arg → repr 截断 + args_coerced=True。
    logging.getLogger("questor.demo").info("run=%s", _RunLike())
    e = harness.got[-1]
    assert e.fields.get("args_coerced") is True
    assert "<Run run_id=abc>" in e.msg  # repr 保留（有界），非原样丢失


def test_coerced_arg_still_redacted(harness: _Sink) -> None:
    # repr 里带 sk- 也必过脱敏（pipeline 单点），且不泄原串。
    logging.getLogger("questor.demo").info("leak=%s", _Leaky())
    e = harness.got[-1]
    assert "sk-abcdef1234567890WXYZ" not in e.msg
    assert e.fields.get("args_coerced") is True
    assert e.fields.get("redacted") is True


def test_scalar_args_not_coerced(harness: _Sink) -> None:
    logging.getLogger("questor.demo").info("x=%s", 42)
    e = harness.got[-1]
    assert "args_coerced" not in e.fields
    assert e.msg == "x=42"


def test_non_questor_logger_not_coerced(harness: _Sink) -> None:
    logging.getLogger("other.app").info("obj=%s", _RunLike())
    e = harness.got[-1]
    assert "args_coerced" not in e.fields  # 白名单只管 questor.*
    assert e.logger == "other.app"


def test_log_fields_is_the_only_extra_entry(harness: _Sink) -> None:
    logging.getLogger("questor.demo").info("m", extra={"log_fields": {"tool": "read"}})
    e = harness.got[-1]
    assert e.fields["tool"] == "read"


def test_traceback_has_no_blank_lines(harness: _Sink) -> None:
    # G-L12：异常链格式化后压掉空行。
    try:
        raise ValueError("boom-g12")
    except ValueError:
        logging.getLogger("questor.demo").error("failed", exc_info=True)
    e = harness.got[-1]
    assert e.traceback is not None
    assert "\n\n" not in e.traceback
    assert all(line.strip() for line in e.traceback.splitlines())
    assert "boom-g12" in e.traceback


def test_context_taken_from_bind(harness: _Sink) -> None:
    from questor.observability.scope import bind

    with bind(run_id="r9", turn=4):
        logging.getLogger("questor.demo").info("corr")
    e = harness.got[-1]
    assert e.context["run_id"] == "r9"
    assert e.context["turn"] == 4


def test_level_mapping(harness: _Sink) -> None:
    from questor.observability.entry import LogLevel

    logging.getLogger("questor.demo").warning("w")
    assert harness.got[-1].level is LogLevel.WARNING


def test_noisy_whitelist_pins_warning() -> None:
    quiet_noisy_loggers()
    assert logging.getLogger("httpx").getEffectiveLevel() == logging.WARNING
