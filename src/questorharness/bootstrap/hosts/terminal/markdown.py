"""流式 markdown 的块状态机：只决定"现在能不能画"，不负责画。

参照 Reasonix `termrender/md.go` 的块切分思路与 DeepCode
`cli/tui/markdown_stream.py` 的验收口径，规则收窄成三条：

1. 未闭合围栏（``` / ~~~）从围栏那一行起整段押住——否则后续文本会被当成代码块；
2. 表格行、列表项的半行押住，整行到达才画，避免"先画半行再重画"；
3. 其余文本即时输出：逐字流式是终端可读性的底线，不能被缓冲吃掉。

`feed()` 是纯函数（输入是**累计文本**，输出 `(可画前缀, 待押后缀)`），
渲染器只需记住待押后缀，下一帧拼接后重新调用。
"""

from __future__ import annotations

FENCE_MARKERS = ("```", "~~~")
HOLD_PREFIXES = ("|", "- ", "* ", "+ ", *FENCE_MARKERS)
_INDENT = " "


def _fence_open_offset(text: str) -> int | None:
    """返回未闭合围栏所在行的起始偏移；没有开着的围栏则返回 None。"""

    offset = 0
    open_offset: int | None = None
    for line in text.splitlines(keepends=True):
        if line.lstrip(_INDENT).startswith(FENCE_MARKERS):
            open_offset = None if open_offset is not None else offset
        offset += len(line)
    return open_offset


def _starts_holdable_line(partial: str) -> bool:
    """半行是否属于"必须整行才能画"的块（表格/列表/围栏）。"""

    stripped = partial.lstrip(_INDENT)
    return stripped.startswith(HOLD_PREFIXES)


def feed(text: str) -> tuple[str, str]:
    """把累计文本切成 `(可画前缀, 待押后缀)`。"""

    if not text:
        return "", ""

    fence_at = _fence_open_offset(text)
    if fence_at is not None:
        return text[:fence_at], text[fence_at:]

    if text.endswith("\n"):
        return text, ""

    newline_at = text.rfind("\n")
    partial = text[newline_at + 1 :]
    if partial and _starts_holdable_line(partial):
        return text[: newline_at + 1], partial
    return text, ""


def flush(text: str) -> str:
    """回合结束/块结束：把待押后缀原样交出来（绝不丢字）。"""

    return text


def block_kind(text: str) -> str:
    """待押后缀属于哪种块，供界面标"正在写代码块/表格"。"""

    stripped = text.lstrip(_INDENT)
    if stripped.startswith(FENCE_MARKERS):
        return "fence"
    if stripped.startswith("|"):
        return "table"
    if stripped.startswith(("- ", "* ", "+ ")):
        return "list"
    return "text"
