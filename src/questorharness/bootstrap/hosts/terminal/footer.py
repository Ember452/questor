"""底部状态栏：模型 · 上下文 · 费用 · 权限模式 · 分支 · 队列。

字段全部可选：波 D 之前 `cost` / `contextWindow` / `branch` 还拿不到真值，
缺失一律渲染 `—`（可见的空，而不是静默的空白）。这一层同时负责把
`terminal_theme.status_bar()` 接活——此前它是零调用点的死代码（plan03 F1）。
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text

from questorharness.bootstrap.hosts.serve import terminal_theme as theme
from questorharness.bootstrap.hosts.terminal import strings


@dataclass(frozen=True)
class FooterVM:
    profile: str
    model: str | None = None
    effort: str | None = None
    permission_mode: str | None = None
    context_used: int | None = None
    context_window: int | None = None
    cost_usd: float | None = None
    branch: str | None = None
    busy: bool = False
    queue_depth: int = 0


def _context(vm: FooterVM) -> str:
    if vm.context_used is None:
        return strings.PLACEHOLDER
    if vm.context_window:
        share = int(vm.context_used * 100 / vm.context_window)
        return f"{vm.context_used}/{vm.context_window} ({share}%)"
    return str(vm.context_used)


def render(vm: FooterVM) -> Text:
    """一行状态栏；每段之间统一用 ` · ` 分隔（对齐 Reasonix chrome 的 status span）。"""

    text = theme.status_bar(vm.profile, vm.model, vm.busy)
    if vm.effort:
        text.append(f" · {vm.effort}", style=theme.DIM)
    text.append(" · ctx ", style=theme.DIM)
    text.append(_context(vm), style=theme.DIM)
    text.append(" · $", style=theme.DIM)
    text.append(
        strings.PLACEHOLDER if vm.cost_usd is None else f"{vm.cost_usd:.4f}",
        style=theme.DIM,
    )
    text.append(" · ", style=theme.DIM)
    text.append(vm.permission_mode or strings.PLACEHOLDER, style=theme.DIM)
    text.append(" · ", style=theme.DIM)
    text.append(vm.branch or strings.PLACEHOLDER, style=theme.DIM)
    if vm.queue_depth:
        text.append(f" · 队列 {vm.queue_depth}", style=theme.WARN)
    return text
