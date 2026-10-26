"""`:` 面板：可选项列表 + 搜索 + 选中即回一条命令。

数据来自 `terminal.app.panel_items`（与行式 REPL 同一真源），命令模板来自
`terminal.pickers`（`PANELS` / `ALIASES` / `action_line`）——这里只负责**怎么选**，
不重写任何命令语义。

为什么不用 `terminal.overlay`：那是 prompt_toolkit 的 alt-screen owner，
在 Textual 里跑会抢屏（plan03 §2.4 的 alt-screen 归属）。Textual 自己的
`ModalScreen` 才是这一层的正确 owner。
"""

from __future__ import annotations

from typing import Any, ClassVar

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from questorharness.bootstrap.hosts.serve import terminal_theme as theme
from questorharness.bootstrap.hosts.terminal import pickers, strings, width
from questorharness.bootstrap.hosts.terminal.pickers import filter_items

__all__ = ["PanelScreen", "filter_items"]


#: 面板里可搜索的字段（与行式 REPL 的过滤口径一致）。
SEARCH_FIELDS = pickers.SEARCH_FIELDS


def _row_text(item: dict[str, Any]) -> str:
    """一行展示文本：`*` 标当前项，标签 + 详情（按宽度截断）。"""

    mark = "*" if item.get("current") else " "
    label = str(item.get("label", item.get("id", "")))
    detail = str(item.get("detail", ""))
    text = f"{mark} {label}" + (f"  {detail}" if detail else "")
    return width.truncate(text, 96)


class PanelScreen(ModalScreen[str]):
    """一个只读列表：Enter 选中返回 id，Esc 取消。"""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "cancel", "取消")]

    def __init__(self, panel: pickers.Panel, items: list[dict[str, Any]]) -> None:
        super().__init__()
        self._panel = panel
        self._items = [dict(item) for item in items]
        self._visible: list[dict[str, Any]] = list(self._items)

    def compose(self) -> ComposeResult:
        yield Container(
            Static(Text(self._panel.title, style=theme.BOLD)),
            Input(placeholder="搜索…（回车选中，Esc 取消）", id="panel-search"),
            OptionList(id="panel-list"),
            Static(Text(strings.PANEL_HINT, style=theme.DIM)),
            id="panel-box",
        )

    def on_mount(self) -> None:
        self._fill()
        self.query_one("#panel-search", Input).focus()

    def _fill(self) -> None:
        listing = self.query_one("#panel-list", OptionList)
        listing.clear_options()
        if not self._visible:
            listing.add_option(Option(Text(strings.NO_MATCH_HINT, style=theme.WARN), id=None))
            return
        listing.add_options(
            [Option(Text(_row_text(item)), id=str(index)) for index, item in enumerate(self._visible)]
        )
        listing.highlighted = 0

    @on(Input.Changed, "#panel-search")
    def _filter(self, event: Input.Changed) -> None:
        self._visible = filter_items(self._items, event.value)
        self._fill()

    @on(Input.Submitted, "#panel-search")
    def _accept_from_search(self) -> None:
        if self._visible:
            self.dismiss(str(self._visible[0].get("id", "")))

    @on(OptionList.OptionSelected, "#panel-list")
    def _pick(self, event: OptionList.OptionSelected) -> None:
        if event.option.id is None:
            return
        index = int(event.option.id)
        if 0 <= index < len(self._visible):
            self.dismiss(str(self._visible[index].get("id", "")))

    def action_cancel(self) -> None:
        self.dismiss(None)
