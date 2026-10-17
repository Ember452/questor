"""Issue #138 判据：日志装配口径（env 族 + payload 门）由 ``surfaces/_assembly`` 单点提供。

旧行为：``__main__`` 有一套完整的 env 解析，而 ``surfaces/cli.main()`` 裸调 ``configure_logging()``
—— 第二个生产入口既不建文件面也无视 ``QUESTOR_LOG_PAYLOAD`` 门，"组合根唯一装配口径"碎成两半。
本文件只锁**解析口径**；两个入口真跑起来的一致性见 ``tests/integration/test_log_entry_parity.py``。
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest

from questor.observability import configure as configure_mod
from questor.observability import exporter as exp_mod
from questor.observability import pipeline
from questor.surfaces import _assembly


@pytest.fixture
def clean_assembly() -> Iterator[None]:
    """save/restore 全部进程级装配态（root handler+级别、questor 子树级别、注册表、管线、单例态）。"""
    root = logging.getLogger()
    first_party = logging.getLogger("questor")
    saved_handlers, saved_level, saved_fp = list(root.handlers), root.level, first_party.level
    saved_registry = list(exp_mod._registry)
    pipeline.reset()
    configure_mod._state = None
    try:
        yield
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
        first_party.setLevel(saved_fp)
        exp_mod._registry[:] = saved_registry
        pipeline.reset()
        configure_mod._state = None


def test_assemble_logging_honors_env_family(clean_assembly: None, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # noqa: ANN001
    logs = tmp_path / "logs"
    monkeypatch.setenv("QUESTOR_LOG_DIR", str(logs))
    monkeypatch.setenv("QUESTOR_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("QUESTOR_LOG_KEEP_DAYS", "3")
    monkeypatch.delenv("QUESTOR_LOG_PAYLOAD", raising=False)

    _assembly.assemble_logging()

    status = configure_mod.logging_status()
    assert logs.is_dir(), "env 指定的文件面必须真建起来（裸装配的旧入口就是没建）"
    assert status["console_level"] == "WARNING"
    assert status["log_dir"] == str(logs)


def test_assemble_logging_keeps_payload_gate(clean_assembly: None, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # noqa: ANN001
    """``QUESTOR_LOG_PAYLOAD`` 的非 off 值必须拒绝启动，不能让以为有载荷的用户扑空。"""
    monkeypatch.setenv("QUESTOR_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("QUESTOR_LOG_PAYLOAD", "on")
    with pytest.raises(SystemExit):
        _assembly.assemble_logging()


def test_bad_keep_days_falls_back_instead_of_crashing(monkeypatch: pytest.MonkeyPatch) -> None:
    # 装配期绝不因一个坏数字而崩（env 解析的容错口径）。
    monkeypatch.setenv("QUESTOR_LOG_KEEP_DAYS", "not-a-number")
    assert _assembly.keep_days_from_env() == 14


def test_assemble_logging_emits_first_party_line(clean_assembly: None, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # noqa: ANN001
    """装配完成必须留一条一方记录——DoD A① 的"起手有日志"靠它兑现，不靠第三方噪声。"""
    monkeypatch.setenv("QUESTOR_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.delenv("QUESTOR_LOG_LEVEL", raising=False)

    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    probe = logging.getLogger("questor.assembly")
    handler = _Capture()
    probe.addHandler(handler)
    try:
        _assembly.assemble_logging()
    finally:
        probe.removeHandler(handler)

    assert any("logging assembled" in r.getMessage() for r in records), "装配自述行缺失"
