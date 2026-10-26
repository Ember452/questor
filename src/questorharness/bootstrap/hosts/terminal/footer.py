"""底部状态栏：模型 · 上下文 · 费用 · 权限模式 · 分支 · 队列。

两种呈现共用一个视图模型：
- `toolbar_text()` 给 prompt_toolkit 的 `bottom_toolbar`（固定底栏，不进 scrollback）；
- `render()` 给非 TTY / 单次 prompt 回退路径（`console.print` 一行）。

字段全部可选，缺数据一律 `—`（可见的空，而不是静默的空白）；一律按终端列宽
截断，绝不把一行状态条折成两行（80 列实跑撞过）。
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text

from questorharness.bootstrap.hosts.serve import terminal_theme as theme
from questorharness.bootstrap.hosts.terminal import strings, width


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


def summary(vm: FooterVM) -> str:
    """一行纯文本状态条（无样式，按段拼好后交给调用方着色或显示）。"""

    parts = [f" {vm.profile}"]
    if vm.model:
        parts.append(vm.model)
    parts.append("回合进行中" if vm.busy else "空闲")
    if vm.effort:
        parts.append(vm.effort)
    # 没有真值的字段不画：`ctx —` / `$—` 是噪音，而不是信息（实跑反馈）。
    if vm.context_used is not None:
        parts.append(f"ctx {_context(vm)}")
    if vm.cost_usd is not None:
        parts.append(f"${vm.cost_usd:.4f}")
    parts.append(vm.permission_mode or strings.PLACEHOLDER)
    parts.append(vm.branch or strings.PLACEHOLDER)
    if vm.queue_depth:
        parts.append(f"队列 {vm.queue_depth}")
    return " · ".join(parts)


def toolbar_text(vm: FooterVM, columns: int) -> str:
    """固定底栏的内容：状态条本身（按列宽截断，不折行）。"""

    return width.truncate(summary(vm), max(1, columns - 1))


def render(vm: FooterVM, columns: int | None = None) -> Text:
    """单行状态条（rich Text）；给了 `columns` 就按列宽截断。"""

    text = theme.status_bar(vm.profile, vm.model, vm.busy)
    if vm.effort:
        text.append(f" · {vm.effort}", style=theme.DIM)
    if vm.context_used is not None:
        text.append(" · ctx ", style=theme.DIM)
        text.append(_context(vm), style=theme.DIM)
    if vm.cost_usd is not None:
        text.append(" · $", style=theme.DIM)
        text.append(f"{vm.cost_usd:.4f}", style=theme.DIM)
    text.append(" · ", style=theme.DIM)
    text.append(vm.permission_mode or strings.PLACEHOLDER, style=theme.DIM)
    text.append(" · ", style=theme.DIM)
    text.append(vm.branch or strings.PLACEHOLDER, style=theme.DIM)
    if vm.queue_depth:
        text.append(f" · 队列 {vm.queue_depth}", style=theme.WARN)
    if columns:
        text.truncate(columns, overflow="ellipsis")
    return text
