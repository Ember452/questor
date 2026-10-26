"""粘贴归一化：去掉终端包裹的括号粘贴标记、统一换行，其余内容一字不改。

只做"归一化"这一件事。多行粘贴的二次确认、图片粘贴的拦截都**没有接线**，
所以这里也不再声明这些能力——留着没有调用方的判定函数等于向用户承诺
一个不存在的行为（同 ADR-0005 §4 的判例）。
"""

from __future__ import annotations

from typing import Final

BRACKETED_PASTE_START: Final[str] = "\x1b[200~"
BRACKETED_PASTE_END: Final[str] = "\x1b[201~"


def strip_markers(text: str) -> str:
    """去掉终端包裹的括号粘贴标记（它们不是用户输入的内容）。"""

    return text.replace(BRACKETED_PASTE_START, "").replace(BRACKETED_PASTE_END, "")


def normalize(text: str) -> str:
    """统一换行并去掉包裹标记，保持其余内容一字不改。"""

    return strip_markers(text).replace("\r\n", "\n").replace("\r", "\n")
