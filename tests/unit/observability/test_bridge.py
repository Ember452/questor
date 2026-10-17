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
from questor.observability.bridge import NOISY_LOGGERS, BridgeHandler, quiet_noisy_loggers
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


def test_noisy_whitelist_uses_the_real_logger_names() -> None:
    """#129：stdlib logger 名大小写敏感——白名单必须用 litellm 真实写的 ``LiteLLM``。

    旧名单只列了小写 ``litellm``，所以整条降噪对其从未生效（实测 quiet 后 ``LiteLLM`` 仍为 NOTSET）。
    同理 ``aiosqlite``——它会把 SQL + 完整参数元组打出来，必须一起钉住。
    """
    quiet_noisy_loggers()
    for name in ("litellm", "LiteLLM", "aiosqlite"):
        assert name in NOISY_LOGGERS, f"{name} 未列入降噪名单"
        assert logging.getLogger(name).level == logging.WARNING, f"{name} 没被钉到 WARNING"


# ---------------------------------------------------------------------------
# Issue #133：桥里撞关联键 / 非标量字段都不得把整行弄丢。
# ---------------------------------------------------------------------------


def test_log_fields_colliding_with_bind_context_keeps_the_line(harness: _Sink) -> None:
    """撞键旧行为：fields 与 context 同名 → ``LogEntry`` 不变式 5 抛错 → 整行静默消失。

    现在关联键优先留在 context，用户那份改 ``f_`` 前缀保留，并标 ``fields_collapsed``。
    """
    from questor.observability.scope import bind

    with bind(run_id="r7"):
        logging.getLogger("questor.demo").info("collision", extra={"log_fields": {"run_id": "explicit"}})
    e = harness.got[-1]
    assert e.msg == "collision", "撞键不得丢整行"
    assert e.context["run_id"] == "r7"
    assert e.fields["f_run_id"] == "explicit"
    assert e.fields.get("fields_collapsed") is True


def test_non_scalar_log_field_is_coerced_not_dropped(harness: _Sink) -> None:
    """D11 的端到端真相：领域对象进 ``log_fields`` 后行仍在，值被有界 repr 而非丢行。

    旧行为只在建 LogEntry 时抛 TypeError（在 handler 里→handleError），业务调用处不炸、日志行没——
    与 entry.py docstring “当场炸”的宣称不符。现在走与 §16.1 args 政策同一套强转。
    """
    logging.getLogger("questor.demo").info("obj-field", extra={"log_fields": {"run": _RunLike()}})
    e = harness.got[-1]
    assert e.msg == "obj-field"
    assert e.fields["run"] == "<Run run_id=abc>"
    assert e.fields.get("args_coerced") is True


def test_reserved_field_name_is_prefixed_not_overwritten(harness: _Sink) -> None:
    """用户传 ``filename`` 不该被桥的调用点覆盖掉（静默改义比报错更难查）。"""
    logging.getLogger("questor.demo").info("reserved", extra={"log_fields": {"filename": "mine.py"}})
    e = harness.got[-1]
    assert e.fields["filename"] != "mine.py"  # 桥的权威调用点保留
    assert e.fields["f_filename"] == "mine.py"
    assert e.fields.get("fields_collapsed") is True
