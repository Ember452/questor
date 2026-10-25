"""粘贴保护：多行粘贴不当命令执行；图片粘贴交给 A5 徽标告知。

终端里最伤人的一类事故：用户粘贴一段日志，第二行恰好是命令，回车即执行。
这里给出判定函数，由输入层决定“直接回车”还是“再确认一次”。
"""

from __future__ import annotations

from typing import Final

BRACKETED_PASTE_START: Final[str] = "\x1b[200~"
BRACKETED_PASTE_END: Final[str] = "\x1b[201~"
IMAGE_MARKERS: Final[tuple[str, ...]] = (
    "\x1b]1337;File=",  # iTerm2 inline image
    "data:image/png;base64,",
    "data:image/jpeg;base64,",
)
MULTILINE_CONFIRM_THRESHOLD: Final[int] = 2


def strip_markers(text: str) -> str:
    """去掉终端包裹的括号粘贴标记（它们不是用户输入的内容）。"""

    return text.replace(BRACKETED_PASTE_START, "").replace(BRACKETED_PASTE_END, "")


def is_image_paste(text: str) -> bool:
    """粘贴内容是不是图片（是则走 A5 徽标告知，而不是丢进 prompt）。"""

    return any(marker in text for marker in IMAGE_MARKERS)


def needs_confirmation(text: str) -> bool:
    """多行粘贴需要二次确认（回车不直接提交）。"""

    lines = [line for line in strip_markers(text).splitlines() if line.strip()]
    return len(lines) >= MULTILINE_CONFIRM_THRESHOLD


def normalize(text: str) -> str:
    """统一换行并去掉包裹标记，保持其余内容一字不改。"""

    return strip_markers(text).replace("\r\n", "\n").replace("\r", "\n")
