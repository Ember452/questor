"""L0' exporter 协议与注册表：``Exporter`` + ``register()``/``current_exporters()``。

三层归属（DESIGN §3）：**内核文件**——运行时 import 只含 stdlib；``LogEntry`` 仅 ``TYPE_CHECKING``。

设计上：协议留内（``Exporter.emit``）、sink 实现各自注册进来。
``register`` 返回**幂等**注销 callable：装配可反复 force 重配而不叠加重复 sink（DESIGN §11 幂等）。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:  # 仅类型：运行时不 import questor.*，内核零外部依赖（G-L1）。
    from questor.observability.entry import LogEntry


class Exporter(Protocol):
    """日志出口协议：接收已治理（脱敏/节流/级别过滤后）的 ``LogEntry``。

    实现方（console/file/llm sink）只需提供 ``emit``。``emit`` 内异常由 pipeline 兜住、绝不上冒
    （D13），故 exporter 无需自我 try/except 保护主循环。
    """

    def emit(self, entry: LogEntry) -> None: ...


# 模块级有序注册表：fan-out 顺序 = 注册顺序（DESIGN §0 管线末端）。
_registry: list[Exporter] = []


def register(exporter: Exporter) -> Callable[[], None]:
    """把 ``exporter`` 追加到 fan-out 尾部，返回一个**幂等**的注销 callable。

    返回的 callable 可安全重复调用（第二次起为 no-op）；装配层据此做 force 重配而不叠加。
    """
    _registry.append(exporter)

    def _unregister() -> None:
        # 幂等：重复注销或已被别处移除时静默（list.remove 缺失会抛 ValueError）。
        try:
            _registry.remove(exporter)
        except ValueError:
            pass

    return _unregister


def current_exporters() -> tuple[Exporter, ...]:
    """返回当前注册表的有序快照（pipeline fan-out 按此顺序 emit）。"""
    return tuple(_registry)
