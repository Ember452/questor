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

#: 补全菜单的行数预算：6 行在 110 条命令面前只够看到一屏噪音，10 行才够用。
MENU_ROWS = 10


def build(
    catalog: Mapping[str, str],
    *,
    history_path: Path | None = None,
    base: Path | None = None,
    key_bindings: Any | None = None,
) -> Any | None:
    """建一个 PromptSession；非 TTY 或缺依赖时返回 None（调用方回退裸 input）。"""

    if not sys.stdin.isatty():
        return None
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.completion import merge_completers
        from prompt_toolkit.history import FileHistory
    except ImportError:
        return None

    history = None
    if history_path is not None:
        history_path.parent.mkdir(parents=True, exist_ok=True)
        history = FileHistory(str(history_path))

    try:
        return PromptSession(
            history=history,
            completer=merge_completers([SlashCompleter(catalog), FileCompleter(base)]),
            complete_while_typing=True,
            enable_history_search=True,
            reserve_space_for_menu=MENU_ROWS,
            key_bindings=key_bindings,
            multiline=True,
            prompt_continuation=lambda width_, line_number, wrap_count: [],
        )
    except Exception:  # noqa: BLE001 - 无控制台宿主（CI/无头 isatty 说谎）构造会抛
        return None
