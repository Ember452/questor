"""L3 工具注册表 + run 内工具面冻结（design/03 §6；04 §6；ADR-0018）。

注册表持有*下一个 run*可见的工具集；`freeze_for_run` 取一份快照（工具对象 + 已 sanitize
的 spec + 只读名映射），之后热更（register/unregister）只影响下一次 freeze，绝不改变已在
跑的 run（防模型看到中途变化的工具面）。description 注册期做 sanitize + 长度界。
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace

from questor.contracts.tool import RunToolSurface, Tool, ToolSpec

_log = logging.getLogger("questor.tools")

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s+")
_DESCRIPTION_MIN = 20
_DESCRIPTION_MAX = 2000


def _sanitize_description(spec: ToolSpec) -> ToolSpec:
    """去控制字符、折叠空白、截上限；过短则退化为含工具名的说明。

    只收紧不外传原文：过长/含注入字符的 description 不能进入 provider 工具面。
    """
    cleaned = bound_description(spec.description, name=spec.name, max_chars=spec.description_max_chars)
    if cleaned != spec.description:
        return replace(spec, description=cleaned)
    return spec


def bound_description(text: str, *, name: str, max_chars: int | None) -> str:
    """共享描述净化（C08 单一真源）：内置工具、skills 目录、未来的 MCP 远程描述都走这一套规则。

    去控制字符 → 折叠空白 → 过短退化（含工具名、绝不空）→ 超界截断加省略号。行为与原
    `_sanitize_description` 逐字一致（抽出仅为复用，不改语义）。
    """
    cleaned = _WHITESPACE.sub(" ", _CONTROL_CHARS.sub("", text)).strip()
    limit = max(_DESCRIPTION_MIN, min(max_chars or _DESCRIPTION_MAX, _DESCRIPTION_MAX))
    if len(cleaned) < _DESCRIPTION_MIN:
        # 退化：保证 provider 永远看到含工具名、达下限的说明，而不是空/过短 description。
        cleaned = f"{name} tool: {cleaned}".strip()
        if len(cleaned) < _DESCRIPTION_MIN:
            cleaned = f"{cleaned} - minimal tool description".strip()
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1].rstrip() + "…"
    return cleaned


class ToolRegistry:
    """进程内工具注册表（可增删查 + 冻结快照 + 误名候选提示）。"""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._specs: dict[str, ToolSpec] = {}
        # P9/ADR-0046：能力名册版本号——每次成功 register/unregister 递增，注入 loop 作 capability_probe
        # → 观测到变化即在安全点发 live-only tools_changed（热更只影响下次 freeze，活 run 面不变）。
        self._generation = 0

    @property
    def generation(self) -> int:
        """当前名册版本（供 capability_probe 读）。"""
        return self._generation

    def register(self, tool: Tool) -> None:
        """注册工具（新工具=加注册；改既有工具语义=契约变更，走评审）。

        C21 命名冲突守卫：若同名已被**另一个**工具占用，**拒绝覆盖 + 出声**（first-writer-wins）——
        远程工具伪装/撞内置名时不能静默顶掉既有工具（C17 capability floor 不因远程放宽）。同对象重注册
        （幂等 reload）不算冲突。
        """
        spec = _sanitize_description(tool.spec)
        existing = self._tools.get(spec.name)
        if existing is not None and existing is not tool:
            _log.warning("refusing to register tool '%s': name already claimed (collision kept existing)", spec.name)
            return
        self._tools[spec.name] = tool
        self._specs[spec.name] = spec
        self._generation += 1

    def unregister(self, name: str) -> None:
        existed = self._tools.pop(name, None) is not None
        self._specs.pop(name, None)
        if existed:
            self._generation += 1

    def has(self, name: str) -> bool:
        return name in self._tools

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_available(self) -> tuple[Tool, ...]:
        """列出 available() 为真的工具（特性开关/凭据/平台缺失时隐藏）。"""
        return tuple(tool for name, tool in self._tools.items() if tool.available())

    def definitions(self) -> tuple[ToolSpec, ...]:
        """available 工具的已 sanitize spec（喂 provider）。"""
        return tuple(self._specs[name] for name, tool in self._tools.items() if tool.available())

    def candidates(self, name: str) -> tuple[str, ...]:
        """委托已冻结 surface 的同名逻辑（保持单一真源）。"""
        return self.freeze_for_run("").candidates(name)

    def freeze_for_run(self, run_id: str) -> RunToolSurface:
        """快照当前 available 工具面给这个 run；后续 register/unregister 不影响此快照。"""
        available = [(self._specs[name], tool) for name, tool in self._tools.items() if tool.available()]
        return RunToolSurface(
            tools=tuple(tool for _, tool in available),
            specs=tuple(spec for spec, _ in available),
            _by_name={spec.name: tool for spec, tool in available},
        )


__all__ = ["RunToolSurface", "ToolRegistry", "bound_description"]
