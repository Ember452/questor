"""补全菜单控制器：把补全器候选接进 Reasonix 菜单，并驱动 buffer。

分工：`completion_menu` 是纯逻辑（wants/move/accept/window），本模块只做
"向补全器取候选 → 建菜单 → 按语义改 buffer → 把菜单挂到底部工具栏"。
这样菜单能完全接管 ↑↓/Tab/Enter/Esc，不再依赖 prompt_toolkit 那个拿不到焦点、
也不画 `›` 游标的浮动补全菜单。

对照 `DeepSeek-Reasonix/internal/frontend/tui/input.go` 的 `onKey`：
`menuKey` 在 composer 之前吃掉菜单键；本模块的 move/accept/should_accept_on_enter
即那三条语义，键位装配在 `keymap.py`。
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from questorharness.bootstrap.hosts.terminal import completion_menu, strings

if TYPE_CHECKING:
    from prompt_toolkit.buffer import Buffer


class MenuController:
    """一个会话一个控制器：持有当前菜单、补全器与（可选）底部工具栏宿主。"""

    def __init__(self, completer: Any | None = None) -> None:
        self._completer = completer
        self._menu: completion_menu.Menu | None = None
        self._session: Any | None = None
        # accept 写回 buffer 会触发 on_text_changed → refresh；用开关挡住这一次
        self._suppress = False

    # ---- 装配 -----------------------------------------------------------
    def bind_completer(self, completer: Any) -> None:
        """补全器在会话建好后才有；绑定前 refresh 视为无候选。"""

        self._completer = completer

    def attach(self, session: Any) -> None:
        """挂到 PromptSession 上：是否显示菜单通过它的 bottom_toolbar 开关。"""

        self._session = session

    @property
    def menu(self) -> completion_menu.Menu | None:
        return self._menu

    @property
    def active(self) -> bool:
        return self._menu is not None and bool(self._menu.rows)

    # ---- 语义 -----------------------------------------------------------
    def refresh(self, buffer: Buffer, *, force: bool = False) -> None:
        """编辑后重算菜单：补全上下文消失就关，否则重建并保留原选中项。"""

        if self._suppress:
            return
        text = buffer.text
        cursor = buffer.cursor_position
        if not completion_menu.wants_menu(text, cursor, force=force):
            self._apply(None)
            return
        completions = self._completions(text, cursor)
        rows = [
            completion_menu.MenuRow(
                label=_completion_text(completion, "display_text") or completion.text,
                insert=completion.text,
                hint=_completion_text(completion, "display_meta_text"),
            )
            for completion in completions
        ]
        if not rows:
            self._apply(None)
            return
        menu = completion_menu.build(
            rows,
            cursor + completions[0].start_position,
            cursor,
            kind="slash" if text[:cursor].startswith("/") else "path",
        )
        if menu is not None:
            self._keep_selection(menu)
        self._apply(menu)

    def move(self, buffer: Buffer, delta: int) -> bool:
        """↑/↓/Ctrl-P/Ctrl-N：菜单开着就环形移动并返回 True（键被吃掉）。"""

        del buffer
        if not self.active or self._menu is None:
            return False
        completion_menu.move(self._menu, delta)
        self._show_toolbar(True)
        self._invalidate()
        return True

    def accept(self, buffer: Buffer) -> bool:
        """Tab/Enter（补全分支）：用选中项替换 token；目录补全保持菜单开在下一层。"""

        if not self.active or self._menu is None:
            return False
        new_text, new_cursor = completion_menu.accept_text(self._menu, buffer.text)
        row = self._menu.selected()
        descend = bool(row is not None and row.insert.endswith("/"))
        self._menu = None
        self._replace_text(buffer, new_text, new_cursor)
        if descend:
            self.refresh(buffer, force=True)
        else:
            self._apply(None)
        return True

    def should_accept_on_enter(self, buffer: Buffer) -> bool:
        """Enter 该接受补全（True）还是提交整行（False）。"""

        if not self.active or self._menu is None:
            return False
        return completion_menu.should_accept_on_enter(self._menu, buffer.text)

    def close(self, buffer: Buffer) -> bool:
        """Esc：关掉菜单并返回 True；菜单没开就不拦键。"""

        del buffer
        if not self.active:
            return False
        self._apply(None)
        return True

    # ---- 渲染 -----------------------------------------------------------
    def toolbar(self) -> list[tuple[str, str]]:
        """交给 prompt_toolkit `bottom_toolbar` 的格式化文本（菜单每行一段）。"""

        menu = self._menu
        if menu is None or not menu.rows:
            return []
        fragments: list[tuple[str, str]] = []
        for index, row in completion_menu.visible_rows(menu):
            selected = index == menu.sel
            style = "class:menu-selected" if selected else ""
            prefix = completion_menu.SELECT_MARKER if selected else completion_menu.INDENT
            fragments.append((style, prefix))
            fragments.append((style, row.label))
            if row.hint:
                fragments.append(("class:menu-hint", "  " + row.hint))
            fragments.append(("", "\n"))
        fragments.append(("class:menu-hint", self._hint_line(menu)))
        return fragments

    # ---- 内部 -----------------------------------------------------------
    def _completions(self, text: str, cursor: int) -> list[Any]:
        if self._completer is None:
            return []
        from prompt_toolkit.completion import CompleteEvent
        from prompt_toolkit.document import Document

        return list(self._completer.get_completions(Document(text, cursor), CompleteEvent()))

    def _keep_selection(self, menu: completion_menu.Menu) -> None:
        previous = self._menu.selected() if self._menu is not None else None
        if previous is None:
            return
        for index, row in enumerate(menu.rows):
            if row.label == previous.label:
                menu.sel = index
                return

    def _replace_text(self, buffer: Buffer, text: str, cursor: int) -> None:
        self._suppress = True
        try:
            buffer.text = text
            buffer.cursor_position = cursor
        finally:
            self._suppress = False

    def _apply(self, menu: completion_menu.Menu | None) -> None:
        self._menu = menu
        self._show_toolbar(self.active)
        self._invalidate()

    def _show_toolbar(self, show: bool) -> None:
        if self._session is None:
            return
        self._session.bottom_toolbar = self.toolbar if show else None

    def _hint_line(self, menu: completion_menu.Menu) -> str:
        return strings.MENU_HINT_FILE if menu.kind == "path" else strings.MENU_HINT_SLASH

    def _invalidate(self) -> None:
        with contextlib.suppress(Exception):  # 单测无 app 上下文；刷新失败不影响语义
            from prompt_toolkit.application.current import get_app

            get_app().invalidate()


def _completion_text(completion: Any, attribute: str) -> str:
    """补全器的 display/meta 可能是格式化文本；只取纯文本，缺失按空串。"""

    value = getattr(completion, attribute, "")
    return value if isinstance(value, str) else ""
