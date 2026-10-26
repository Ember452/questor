"""面板行的搜索口径：唯一实现，两个宿主共用。

`overlay`（行式 REPL）与 `tui/panels`（Textual）都需要"按 id/label/detail
子串过滤"。各写一份的后果不是重复代码，而是**两种口径**——用户会发现
同一个面板在两个界面里搜出来的东西不一样。

无依赖模块（只吃 dict），所以谁能 import 它都不会成环。
"""

from __future__ import annotations

from typing import Any, Final

SEARCH_FIELDS: Final[tuple[str, ...]] = ("id", "label", "detail")


def filter_items(items: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """按 id/label/detail 子串过滤（空查询 = 不过滤，返回副本）。"""

    needle = query.strip().lower()
    if not needle:
        return list(items)
    return [
        item
        for item in items
        if any(needle in str(item.get(field, "")).lower() for field in SEARCH_FIELDS)
    ]
