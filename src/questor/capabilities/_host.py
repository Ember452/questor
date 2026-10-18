"""L3 能力热插拔宿主 PluginHost（design/00 横向 DI；C10；ADR-0046）。

给"能力插件"（工具/技能/MCP 一类有 init/teardown 生命周期的东西）一个**统一生命周期 +
熔断护栏**：``register`` 调 ``init``、``deregister`` 调 ``teardown``，每次调用一律包 try/except
——异常**被捕获、WARN、不外抛、不崩宿主/内核**（C10）。仅捕 ``Exception``：``KeyboardInterrupt``/
``SystemExit``/``CancelledError``（BaseException 子类）如实上抛，绝不把取消吃成静默（承 ADR-0028）。

**不是通用 DI 容器**（ADR-0046）：questor 用手动构造注入 + 组合根已足；本宿主只管"注册点 +
生命周期 + 故障隔离 + generation 计数"。``generation`` 每次成功增删 +1，注入 turn loop 作
``capability_probe``——loop 在安全点据此发 live-only ``tools_changed``（热更只影响下一次 freeze，
活 run 工具面不变，承 ``tools/registry.py:97-104``）。

**边界（C1）**：只 import 标准库 + ``contracts``；不 import surfaces/providers 具体实现。
发现≠执行（inert discovery，借 DeepCode ``plugins/host.py`` 纪律）：本宿主不扫盘、不执行插件代码副作用。
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

_log = logging.getLogger("questor.plugin_host")


@runtime_checkable
class PluginLifecycle(Protocol):
    """能力插件的最小生命周期契约（ADR-0046）。实现体住在各能力层、由宿主统一编排。

    ``init``/``teardown`` 允许抛错——宿主一律熔断包裹（C10）；它们不得做超职责的写状态/裸 IO
    副作用（那是内核/端口的活，见 design/05 §0 边界）。"""

    id: str

    def init(self) -> None: ...

    def teardown(self) -> None: ...


class PluginHost:
    """进程内插件注册表 + 生命周期编排 + 故障隔离 + generation 计数。"""

    def __init__(self) -> None:
        self._plugins: dict[str, PluginLifecycle] = {}
        self._generation = 0

    @property
    def generation(self) -> int:
        """能力名册版本号：每次成功 register/deregister 递增（供 loop 观测→发 tools_changed）。"""
        return self._generation

    def generation_probe(self) -> int:
        """返回当前 generation 的可调用探针（注入 ``DefaultTurnLoop.capability_probe``）。"""
        return self._generation

    def ids(self) -> set[str]:
        """当前已激活插件 id 集。"""
        return set(self._plugins)

    def register(self, plugin: PluginLifecycle) -> bool:
        """注册并 ``init``。init 抛错 → WARN、不激活、不 bump generation、返回 False（不外抛）。"""
        pid = getattr(plugin, "id", "<no-id>")
        try:
            plugin.init()
        except Exception as exc:  # noqa: BLE001 - 熔断：插件 init 崩不得带崩宿主（C10）；BaseException 已先上抛
            _log.warning("plugin %r init failed, not registered (isolated): %s", pid, exc)
            return False
        self._plugins[pid] = plugin
        self._generation += 1
        return True

    def deregister(self, plugin_id: str) -> bool:
        """注销并 ``teardown``。teardown 抛错 → WARN 但仍完成注销 + bump generation（不留僵尸）。"""
        plugin = self._plugins.pop(plugin_id, None)
        if plugin is None:
            return False
        try:
            plugin.teardown()
        except Exception as exc:  # noqa: BLE001 - 熔断：teardown 崩不阻断注销（C10）
            _log.warning("plugin %r teardown raised (deregistration still completed): %s", plugin_id, exc)
        self._generation += 1
        return True


__all__ = ["PluginHost", "PluginLifecycle"]
