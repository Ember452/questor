"""Profile 形态数据：一份 bundle 描述一种产品形态。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ProfileInfo:
    """一个形态的完整描述（人设 / 模型 / 技能 / 工具 / 界面能力位）。"""

    name: str
    path: Path
    description: str = ""
    model: str | None = None
    provider: str | None = None
    skill_dirs: tuple[str, ...] = ()
    plugin_roots: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    denied_tools: tuple[str, ...] = ()
    ui_capabilities: Mapping[str, str] = field(default_factory=dict)
    runtime_capabilities: Mapping[str, str] = field(default_factory=dict)
    is_default: bool = False
