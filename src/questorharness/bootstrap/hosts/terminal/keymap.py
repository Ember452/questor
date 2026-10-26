"""输入层的键位：Enter 提交 · Alt+Enter 换行 · Tab 补全 · Ctrl-C 中止 · Ctrl-D 退出。

Reasonix 的键位表按模式分文件（`tui/vimode.go` / `input.go`）；本项目只需要
几条语义，所以集中在这里，并由 `tests/unit/bootstrap/hosts/terminal/test_keymap.py`
钉住"声明了就有行为"（同 ADR-0005 §4 的判例）。

`multiline=True` 之后 Enter 默认变成换行；这里把它改回**提交**，换行交给
Alt+Enter——否则每个习惯"打完回车"的用户都会以为程序卡住。
"""

from __future__ import annotations

from typing import Any


def build(menu: Any | None = None) -> Any:
    """构造 prompt_toolkit KeyBindings；缺依赖时返回 None（回退裸 input 路径）。

    语义与 plan03 的 Ctrl-C 四语义表一致：
    - 输入框：清行（不退出）——由 `prompt_toolkit` 的 abort 触发 KeyboardInterrupt，
      `app.read_line` 把它转成中断哨兵；
    - 回合中：哨兵变成 `POST /cancel`（见 `app.drive_turns`）；
    - Ctrl-D：EOF，退出前收完已受理回合；
    - Ctrl-L：清屏重画（终端惯例，避免长输出刷屏后上下文丢失）。

    菜单键（Reasonix `menuKey` 语义）：菜单开着时 ↑↓/Ctrl-P/Ctrl-N 环形移动、
    Tab/Enter 接受（Enter 仅在"行已成前缀"时接受，否则提交）、Esc 关闭；
    菜单没开时 ↑↓/Ctrl-P/Ctrl-N 回落历史与光标移动，与默认键位一致。
    """

    try:
        from prompt_toolkit.filters import Condition
        from prompt_toolkit.key_binding import KeyBindings
    except ImportError:  # pragma: no cover - 输入层可选依赖
        return None

    bindings = KeyBindings()
    has_menu = Condition(lambda: menu is not None and bool(getattr(menu, "active", False)))

    @bindings.add("c-c")
    def _interrupt(event: Any) -> None:
        """交回控制权：交互循环据此决定清行还是取消回合。"""

        event.app.exit(exception=KeyboardInterrupt, style="class:aborting")

    @bindings.add("c-l")
    def _redraw(event: Any) -> None:
        """清屏重画：保留当前输入行。"""

        event.app.renderer.clear()
        event.app.invalidate()

    @bindings.add("up")
    def _up(event: Any) -> None:
        """↑：菜单开着就移动选中项，否则回落光标/历史。"""

        buffer = event.current_buffer
        if menu is not None and menu.move(buffer, -1):
            return
        buffer.auto_up(count=event.arg)

    @bindings.add("down")
    def _down(event: Any) -> None:
        """↓：菜单开着就移动选中项，否则回落光标/历史。"""

        buffer = event.current_buffer
        if menu is not None and menu.move(buffer, 1):
            return
        buffer.auto_down(count=event.arg)

    @bindings.add("c-p")
    def _prev(event: Any) -> None:
        """Ctrl-P：同 ↑（Reasonix 同款别名）。"""

        buffer = event.current_buffer
        if menu is not None and menu.move(buffer, -1):
            return
        buffer.auto_up(count=event.arg)

    @bindings.add("c-n")
    def _next(event: Any) -> None:
        """Ctrl-N：同 ↓（Reasonix 同款别名）。"""

        buffer = event.current_buffer
        if menu is not None and menu.move(buffer, 1):
            return
        buffer.auto_down(count=event.arg)

    @bindings.add("enter")
    def _submit(event: Any) -> None:
        """Enter：行已成高亮项前缀则接受补全，否则提交（多行模式下也要保住）。"""

        buffer = event.current_buffer
        if menu is not None and menu.should_accept_on_enter(buffer):
            menu.accept(buffer)
            return
        buffer.validate_and_handle()

    @bindings.add("escape", "enter")
    def _newline(event: Any) -> None:
        """Alt+Enter = 换行。"""

        event.current_buffer.insert_text("\n")

    @bindings.add("tab")
    def _complete(event: Any) -> None:
        """Tab：菜单开着就接受选中项；没开就强制开菜单（显式补全入口）。"""

        if menu is None:
            return
        if menu.accept(event.current_buffer):
            return
        menu.refresh(event.current_buffer, force=True)

    @bindings.add("escape", filter=has_menu)
    def _close_menu(event: Any) -> None:
        """Esc：只吞掉"关菜单"；菜单没开时不拦键，Alt+Enter 不受影响。"""

        if menu is not None:
            menu.close(event.current_buffer)

    return bindings
