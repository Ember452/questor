"""L3 工具注册表接缝（design/03 §6）。

工具在此注册；一个 run 内工具集*冻结*，模型不会看到工具中途增减（``tools_changed``
只对下一 run 生效）。具体注册表实现属 P1(T5)。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from questor.contracts.tool import Tool


class ToolRegistry(ABC):
    """持有下一个 run 可用的工具集；仅增/查。"""

    @abstractmethod
    def register(self, tool: Tool) -> None:
        """注册一个工具（新工具=加注册；绝不改既有工具的语义）。"""

    @abstractmethod
    def get(self, name: str) -> Tool | None:
        """按名查找；未知返回 ``None``。"""

    @abstractmethod
    def list_available(self) -> tuple[Tool, ...]:
        """列出 ``available()`` 为真的工具（特性开关/凭据门控）。"""
