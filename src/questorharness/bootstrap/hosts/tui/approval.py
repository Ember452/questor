"""审批模态：工具名 + 目标（一行）+ diff，y/n 或按钮结算。

抽成独立模块有两个原因：`app.py` 已经在 500 行红线边上；审批是唯一
"必须模态化"的交互，单独成文件后它的约束（标题只占一行）才好写注释。
"""

from __future__ import annotations

from typing import Any, ClassVar

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from questorharness.bootstrap.hosts.serve import terminal_theme as theme
from questorharness.bootstrap.hosts.terminal import diff as diff_card
from questorharness.bootstrap.hosts.terminal import width
from questorharness.bootstrap.hosts.terminal import wire_view as view


def approval_head(item: view.ApprovalItem) -> Text:
    """审批模态的标题行：工具名 + 目标（压成一行、截断）。

    只占一行是硬约束：default 模式下 subject 是一整段英文说明，原样塞进
    模态会把框撑成整屏（实跑截图）。
    """

    head = Text()
    head.append("⚠ 需要审批  ", style=theme.ACCENT)
    head.append(item.tool, style=theme.BOLD)
    target = _one_line(item.subject)
    if target:
        head.append("  " + width.truncate(target, 72), style=theme.NET)
    return head


def _one_line(text: str) -> str:
    """压成一行（审批目标通常是长句，多行会把模态撑高）。"""

    return " ".join(text.split())


class ApprovalScreen(ModalScreen[str]):
    """审批模态：y 允许 / n 拒绝（回车默认拒绝，与服务端 fail-closed 一致）。"""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("y", "choose('y')", "允许"),
        Binding("n", "choose('n')", "拒绝"),
        Binding("escape", "choose('n')", "拒绝"),
    ]

    def __init__(self, item: view.ApprovalItem) -> None:
        super().__init__()
        self._item = item

    def compose(self) -> ComposeResult:
        item = self._item
        body: list[Any] = [Static(approval_head(item))]
        if item.patch:
            body.append(
                Static(
                    diff_card.render_patch(
                        item.patch, added=item.added or 0, removed=item.removed or 0
                    )
                )
            )
        elif item.detail:
            body.append(Static(diff_card.render_detail(item.detail)))
        yield Container(
            *body,
            Horizontal(
                Button("允许 y", id="y", variant="success"),
                Button("拒绝 n", id="n", variant="error"),
                classes="approval-actions",
            ),
            id="approval-box",
        )

    @on(Button.Pressed)
    def _pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id or "n")

    def action_choose(self, value: str) -> None:
        self.dismiss(value)
