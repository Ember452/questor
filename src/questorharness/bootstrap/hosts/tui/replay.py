"""`--resume` 的历史回放：把 `/history` 的消息变成可分块挂进对话区的渲染物。

只回放**文本**：工具调用与结果在历史里可能已经过时（文件改过了），把它们
当成"当时发生过的事实"平铺出来会误导；需要细节时 `/history` 面板仍可查。

纯函数，便于在没有终端的测试里钉住形状。
"""

from __future__ import annotations

from typing import Any

from rich.console import RenderableType
from rich.markdown import Markdown
from rich.text import Text

from questorharness.bootstrap.hosts.serve import terminal_theme as theme


def message_text(message: dict[str, Any]) -> str:
    """一条消息里的全部文本块（按顺序拼接）。"""

    blocks = message.get("blocks")
    if not isinstance(blocks, list):
        return ""
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    return "\n\n".join(parts)


def history_renderables(messages: list[dict[str, Any]]) -> list[RenderableType]:
    """历史消息 → 渲染物列表：用户行加 `❯`，助手文本走 Markdown。"""

    out: list[RenderableType] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        text = message_text(message)
        if not text:
            continue
        if str(message.get("role", "assistant")) == "user":
            out.append(Text("❯ " + text, style=theme.BOLD))
        else:
            out.append(Markdown(text))
    return out
