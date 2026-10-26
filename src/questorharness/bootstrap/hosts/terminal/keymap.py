"""输入层的键位：Enter 提交 · Alt+Enter 换行 · Tab 补全 · Ctrl-C 中止 · Ctrl-D 退出。

Reasonix 的键位表按模式分文件（`tui/vimode.go` / `input.go`）；本项目只需要
几条语义，所以集中在这里，并由 `tests/unit/bootstrap/hosts/terminal/test_keymap.py`
钉住"声明了就有行为"（同 ADR-0005 §4 的判例）。

`multiline=True` 之后 Enter 默认变成换行；这里把它改回**提交**，换行交给
Alt+Enter——否则每个习惯"打完回车"的用户都会以为程序卡住。
"""

from __future__ import annotations

from typing import Any


def build() -> Any:
    """构造 prompt_toolkit KeyBindings；缺依赖时返回 None（回退裸 input 路径）。

    语义与 plan03 的 Ctrl-C 四语义表一致：
    - 输入框：清行（不退出）——由 `prompt_toolkit` 的 abort 触发 KeyboardInterrupt，
      `app.read_line` 把它转成中断哨兵；
    - 回合中：哨兵变成 `POST /cancel`（见 `app.drive_turns`）；
    - Ctrl-D：EOF，退出前收完已受理回合；
    - Ctrl-L：清屏重画（终端惯例，避免长输出刷屏后上下文丢失）。
    """

    try:
        from prompt_toolkit.key_binding import KeyBindings
    except ImportError:  # pragma: no cover - 输入层可选依赖
        return None

    bindings = KeyBindings()

    @bindings.add("c-c")
    def _interrupt(event: Any) -> None:
        """交回控制权：交互循环据此决定清行还是取消回合。"""

        event.app.exit(exception=KeyboardInterrupt, style="class:aborting")

    @bindings.add("c-l")
    def _redraw(event: Any) -> None:
        """清屏重画：保留当前输入行。"""

        event.app.renderer.clear()
        event.app.invalidate()

    @bindings.add("enter")
    def _submit(event: Any) -> None:
        """Enter = 提交（多行模式下也要保住这条肌肉记忆）。"""

        event.current_buffer.validate_and_handle()

    @bindings.add("escape", "enter")
    def _newline(event: Any) -> None:
        """Alt+Enter = 换行。"""

        event.current_buffer.insert_text("\n")

    @bindings.add("tab")
    def _complete(event: Any) -> None:
        """Tab 显式打开补全菜单（自动弹出失效时这是兜底入口）。"""

        buffer = event.current_buffer
        if buffer.complete_state:
            buffer.complete_next()
        else:
            buffer.start_completion(select_first=False)

    return bindings
