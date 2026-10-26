"""输入层：prompt_toolkit 会话（多行编辑、斜杠 + 路径补全、历史）与裸 input 回退。

`prompt_toolkit` 只在这里与门面出现（`scripts/guards/check_layout.py` 的目录级放行）。
非 TTY 宿主（管道 / CI）必须能回退到裸 `input()`，否则 `--prompt` 与脚本化调用全断。

多行编辑的键位约定：**Enter 提交**（和所有 CLI 一致，不改变肌肉记忆），
换行走 Alt+Enter（`keymap.py` 里绑定 `escape, enter`）。
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from questorharness.bootstrap.hosts.terminal.completer import FileCompleter, SlashCompleter

#: 菜单配色：选中行加粗（`›` 游标已在文本层画出），说明行暗色。
_MENU_STYLE = {
    "menu-selected": "bold",
    "menu-hint": "fg:#888888",
}


def build(
    catalog: Mapping[str, str],
    *,
    history_path: Path | None = None,
    base: Path | None = None,
    key_bindings: Any | None = None,
    menu: Any | None = None,
) -> Any | None:
    """建一个 PromptSession；非 TTY 或缺依赖时返回 None（调用方回退裸 input）。

    `menu`（`menu_controller.MenuController`）在会话建好后接入：它把补全器候选
    画进 `bottom_toolbar`，并接管 ↑↓/Tab/Enter/Esc——所以这里关掉 prompt_toolkit
    自带的浮动补全菜单（那个菜单拿不到焦点、也不画 `›` 游标）。
    """

    if not sys.stdin.isatty():
        return None
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.completion import merge_completers
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.styles import Style
    except ImportError:
        return None

    history = None
    if history_path is not None:
        history_path.parent.mkdir(parents=True, exist_ok=True)
        history = FileHistory(str(history_path))

    completer = merge_completers([SlashCompleter(catalog), FileCompleter(base)])
    try:
        session: Any = PromptSession(
            history=history,
            completer=completer,
            # 自带浮动菜单关掉：菜单改由 MenuController 自绘到 bottom_toolbar。
            complete_while_typing=False,
            enable_history_search=True,
            key_bindings=key_bindings,
            multiline=True,
            prompt_continuation=lambda width_, line_number, wrap_count: [],
            style=Style.from_dict(_MENU_STYLE),
        )
    except Exception:  # noqa: BLE001 - 无控制台宿主（CI/无头 isatty 说谎）构造会抛
        return None

    if menu is not None:
        menu.bind_completer(completer)
        menu.attach(session)
        # `on_text_changed` 是一个 Event（fire 时把 sender=当前 Buffer 传给处理函数）：
        # 必须 += 追加，不能直接赋值覆盖——覆盖会掉掉 Event 本体，每次敲键都报 'fire' 属性错。
        session.default_buffer.on_text_changed += menu.refresh
    return session
