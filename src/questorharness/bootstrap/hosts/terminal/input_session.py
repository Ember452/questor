"""输入层：prompt_toolkit 会话（斜杠 + 路径补全、历史、粘贴保护）与裸 input 回退。

`prompt_toolkit` 只在这里与门面出现（`scripts/guards/check_layout.py` 的目录级放行）。
非 TTY 宿主（管道 / CI）必须能回退到裸 `input()`，否则 `--prompt` 与脚本化调用全断。
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from questorharness.bootstrap.hosts.terminal import paste
from questorharness.bootstrap.hosts.terminal.completer import FileCompleter, SlashCompleter

_PROMPT = "> "


def build(
    catalog: Mapping[str, str], *, history_path: Path | None = None, base: Path | None = None
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

    return PromptSession(
        history=history,
        completer=merge_completers([SlashCompleter(catalog), FileCompleter(base)]),
        complete_while_typing=True,
        enable_history_search=True,
        reserve_space_for_menu=6,
    )


def prepare_line(raw: str) -> str:
    """粘贴归一化：去括号粘贴标记、统一换行；其余内容一字不改。"""

    return paste.normalize(raw)


def prompt_text() -> str:
    """提示符（Reasonix chrome 的 `❯ `）。"""

    return _PROMPT
