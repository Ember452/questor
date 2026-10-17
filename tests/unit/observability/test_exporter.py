"""T2.5 exporter 协议 ``observability/exporter.py`` 判例（DESIGN §0/§3）。

覆盖：``register`` 返回一个 **幂等** 的注销 callable；fan-out 顺序=注册顺序；注销后不再出现；
重复注销不报错。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from questor.observability.entry import LogEntry, LogLevel
from questor.observability.exporter import Exporter, current_exporters, register


def _entry(msg: str = "x") -> LogEntry:
    from datetime import UTC, datetime

    return LogEntry(ts=datetime.now(UTC), level=LogLevel.INFO, logger="questor.t", msg=msg, source="inline")


class _Collector:
    """最小 Exporter：把收到的 entry 收进列表，供顺序/断言。"""

    def __init__(self) -> None:
        self.got: list[LogEntry] = []

    def emit(self, entry: LogEntry) -> None:
        self.got.append(entry)


@pytest.fixture
def _clean_registry() -> Iterator[list]:
    """每个用例结束把测试期间注册的 exporter 全部注销，保证模块级注册表用例间隔离。"""
    made: list = []
    yield made
    for unreg in made:
        unreg()


def test_protocol_shape() -> None:
    # _Collector 结构满足 Exporter 协议（emit(LogEntry)->None）。
    c: Exporter = _Collector()
    e = _entry()
    c.emit(e)
    assert c.got == [e]


def test_register_appends_and_returns_idempotent_unregister(_clean_registry: list) -> None:
    a = _Collector()
    unreg = register(a)
    _clean_registry.append(unreg)
    assert current_exporters()[-1] is a
    # 幂等：重复注销不报错，且只移除一次。
    unreg()
    unreg()
    assert a not in current_exporters()


def test_fanout_order_is_registration_order(_clean_registry: list) -> None:
    a, b = _Collector(), _Collector()
    ua, ub = register(a), register(b)
    _clean_registry.extend([ua, ub])
    tail = current_exporters()[-2:]
    assert tail == (a, b)
    ub()
    assert current_exporters()[-1] is a
    assert b not in current_exporters()


def test_reregister_same_exporter_reappears(_clean_registry: list) -> None:
    a = _Collector()
    unreg = register(a)
    unreg()
    _clean_registry.append(register(a))  # 再次注册
    assert current_exporters()[-1] is a
