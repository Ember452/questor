"""终端宽度：rich.cells 之上的薄封装（不另立宽度表）。

只做三件 rich 不做的事：Tab 展开、控制字符过滤、按显示宽度截断/折行。
宽度真源永远是 `rich.cells.cell_len`（plan03 §3 宽度行：双真源是错行的经典来源）。
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator

import rich.cells

TAB_SIZE = 4
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_JOINERS = "\ufe0f\u200d"  # variation selector / zero-width joiner


def _sanitize(text: str) -> str:
    """Tab → 空格，去掉控制字符（含换行：本模块按行工作）。"""

    expanded = text.expandtabs(TAB_SIZE)
    return _CONTROL_RE.sub("", expanded)


def cell_len(text: str) -> int:
    """字符串在终端里占的单元格数（CJK/emoji/组合字符交给 rich 判定）。"""

    return rich.cells.cell_len(_sanitize(text))


def clusters(text: str) -> Iterator[str]:
    """按字素簇切分：组合符号、变体选择符与 ZWJ 序列跟上一个簇走。"""

    current = ""
    for char in _sanitize(text):
        joins = bool(current) and (
            unicodedata.combining(char) != 0
            or char in _JOINERS
            or current.endswith(_JOINERS[-1])
        )
        if joins:
            current += char
            continue
        if current:
            yield current
        current = char
    if current:
        yield current


def truncate(text: str, budget: int, *, ellipsis: str = "") -> str:
    """按显示宽度截断，不切开字素簇；省略号只在放得下时才加。"""

    if budget <= 0:
        return ""
    clean = _sanitize(text)
    if cell_len(clean) <= budget:
        return clean
    reserve = cell_len(ellipsis)
    content_budget = budget - reserve if reserve and budget - reserve >= 1 else budget
    kept: list[str] = []
    used = 0
    for cluster in clusters(clean):
        width = cell_len(cluster)
        if used + width > content_budget:
            break
        kept.append(cluster)
        used += width
    return "".join(kept) + (ellipsis if content_budget < budget else "")


def wrap(text: str, budget: int, *, break_on_space: bool = True) -> list[str]:
    """按显示宽度折行；优先在空格处断开，行宽不超过预算。"""

    if budget <= 0:
        raise ValueError("wrap() 需要正数 budget")
    clean = _sanitize(text)
    if not clean:
        return [""]
    if cell_len(clean) <= budget:
        return [clean]

    lines: list[str] = []
    current: list[str] = []
    used = 0
    for cluster in clusters(clean):
        width = cell_len(cluster)
        if used + width > budget and current:
            line = "".join(current)
            if break_on_space and cluster == " " and line:
                lines.append(line.rstrip())
                current, used = [], 0
                continue
            lines.append(line.rstrip())
            current, used = [], 0
            if cluster == " ":
                continue
        current.append(cluster)
        used += width
    if current:
        lines.append("".join(current).rstrip())
    return lines or [""]
