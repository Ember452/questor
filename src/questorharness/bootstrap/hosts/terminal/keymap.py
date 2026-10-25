"""输入层的键位：Ctrl-C 交回中断哨兵、Ctrl-D 退出、Ctrl-L 重画。

Reasonix 的键位表按模式分文件（`tui/vimode.go` / `input.go`）；本项目只需要
三键语义，所以集中在这里，并由 `tests/unit/bootstrap/hosts/terminal/test_keymap.py`
钉住"声明了就有行为"（同 ADR-0005 §4 的判例）。
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

    return bindings
