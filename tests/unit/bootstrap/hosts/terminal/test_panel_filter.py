"""`panel_filter.py`：面板行的搜索口径（行式 REPL 与 TUI 共用的唯一实现）。"""

from __future__ import annotations

from questorharness.bootstrap.hosts.terminal.panel_filter import SEARCH_FIELDS, filter_items

ROWS = [
    {"id": "glm-4.7", "label": "glm-4.7", "detail": "zhipu"},
    {"id": "deepseek-flash", "label": "deepseek-flash", "detail": "deepseek"},
]


def test_empty_query_returns_a_copy_of_every_row() -> None:
    rows = filter_items(ROWS, "   ")
    assert rows == ROWS
    assert rows is not ROWS  # 副本：调用方排序不会改到源


def test_query_matches_id_label_and_detail_case_insensitively() -> None:
    assert [row["id"] for row in filter_items(ROWS, "DEEP")] == ["deepseek-flash"]
    assert [row["id"] for row in filter_items(ROWS, "zhipu")] == ["glm-4.7"]
    assert filter_items(ROWS, "zz") == []


def test_search_fields_are_the_documented_three() -> None:
    """口径变更要显式改这里（否则两个宿主会悄悄不一致）。"""

    assert SEARCH_FIELDS == ("id", "label", "detail")
