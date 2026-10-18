"""P9 T5：能力热插拔宿主 PluginHost（ADR-0046）——统一生命周期 init/teardown + 熔断隔离 + generation。

真依赖判据（DoD④"能力热插拔不崩内核"）：
- register 触发 init、deregister 触发 teardown（生命周期接通）；
- 插件 init/teardown **抛错被熔断**：不外抛、WARN、宿主仍可用、内核不崩（C10）；
- 每次成功 register/deregister bump ``generation``（供 loop 发 live-only tools_changed，字段≠gate 的 gate 在此）。
"""

from __future__ import annotations

import logging

import pytest

from questor.capabilities._host import PluginHost


class _Plugin:
    def __init__(self, pid: str) -> None:
        self.id = pid
        self.initialized = False
        self.torndown = False

    def init(self) -> None:
        self.initialized = True

    def teardown(self) -> None:
        self.torndown = True


class _BadInit(_Plugin):
    def init(self) -> None:  # 构造/加载即炸（模拟破损插件）
        raise RuntimeError("init exploded")


class _BadTeardown(_Plugin):
    def teardown(self) -> None:
        raise RuntimeError("teardown exploded")


def test_register_runs_init_and_bumps_generation() -> None:
    host = PluginHost()
    p = _Plugin("p1")
    assert host.register(p) is True
    assert p.initialized is True
    assert host.generation == 1
    assert "p1" in host.ids()


def test_init_panic_is_isolated_not_raised(caplog) -> None:
    host = PluginHost()
    with caplog.at_level(logging.WARNING, logger="questor.plugin_host"):
        ok = host.register(_BadInit("bad"))
    assert ok is False  # 未注册成功
    assert host.generation == 0  # 未 bump（未激活）
    assert "bad" not in host.ids()
    assert any("bad" in r.message or "init" in r.message.lower() for r in caplog.records)  # 出声
    # 关键：内核/宿主未被带崩，仍可用
    assert host.register(_Plugin("after")) is True


def test_teardown_panic_is_isolated_still_deregistered() -> None:
    host = PluginHost()
    p = _BadTeardown("t1")
    assert host.register(p) is True
    gen0 = host.generation
    # teardown 抛错不得外抛，仍完成注销 + bump generation
    assert host.deregister("t1") is True
    assert "t1" not in host.ids()
    assert host.generation == gen0 + 1


def test_deregister_unknown_is_noop() -> None:
    host = PluginHost()
    assert host.deregister("ghost") is False
    assert host.generation == 0


def test_generation_is_callable_probe() -> None:
    host = PluginHost()
    probe = host.generation_probe  # 注入 loop 的 capability_probe（Callable[[],int]）
    assert probe() == 0
    host.register(_Plugin("x"))
    assert probe() == 1


@pytest.mark.parametrize("n", [1, 2, 3])
def test_repeated_register_deregister_bumps(n: int) -> None:
    host = PluginHost()
    for i in range(n):
        host.register(_Plugin(f"p{i}"))
        host.deregister(f"p{i}")
    assert host.generation == 2 * n
