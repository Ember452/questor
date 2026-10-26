"""`overlay.py`：面板状态机与编号回退（alt-screen 只做同一份内容的另一种画法）。"""

from __future__ import annotations

import asyncio

from questorharness.bootstrap.hosts.terminal import overlay, strings

ITEMS = [
    {"id": "alpha", "label": "alpha", "detail": "第一项"},
    {"id": "beta", "label": "beta", "detail": "第二项", "current": True},
    {"id": "gamma", "label": "gamma"},
]


def _state() -> overlay.PanelState:
    return overlay.PanelState(title="测试面板", items=[dict(item) for item in ITEMS])


def test_selected_defaults_to_the_first_row() -> None:
    assert _state().selected() == {"id": "alpha", "label": "alpha", "detail": "第一项"}


def test_move_clamps_at_both_ends() -> None:
    state = _state()
    overlay.move(state, -1)
    assert state.index == 0
    overlay.move(state, 99)
    assert state.index == 2


def test_empty_panel_has_no_selection_and_says_so() -> None:
    state = overlay.PanelState(title="空", items=[])
    assert state.selected() is None
    assert "（空）" in "\n".join(overlay.render_lines(state))


def test_query_filters_and_resets_the_cursor() -> None:
    state = _state()
    overlay.move(state, 2)
    overlay.set_query(state, "bet")
    assert [row["id"] for row in state.visible()] == ["beta"]
    assert state.index == 0


def test_query_matches_detail_text() -> None:
    state = _state()
    overlay.set_query(state, "第二")
    assert [row["id"] for row in state.visible()] == ["beta"]


def test_render_marks_the_cursor_and_the_current_row() -> None:
    state = _state()
    lines = overlay.render_lines(state)
    assert any("> " in line for line in lines), lines
    assert any("alpha" in line for line in lines)
    assert lines[-1] == strings.PANEL_HINT


def test_render_window_follows_the_cursor() -> None:
    many = [{"id": f"id-{index}", "label": f"行 {index}"} for index in range(40)]
    state = overlay.PanelState(title="长列表", items=many)
    overlay.move(state, 30)
    lines = overlay.render_lines(state, limit=5)
    assert any("行 30" in line for line in lines)


def test_render_inserts_a_header_when_the_group_changes() -> None:
    """命令面板按族分组（plan03 C2/T18）：族变了插一行标题，不硬编码清单。"""

    rows = [
        {"id": "/a", "label": "/a", "group": "session"},
        {"id": "/b", "label": "/b", "group": "session"},
        {"id": "/c", "label": "/c", "group": "model"},
    ]
    state = overlay.PanelState(title="命令", items=rows)
    lines = overlay.render_lines(state)
    headers = [line for line in lines if "──" in line]
    assert len(headers) == 2, lines
    assert "session" in headers[0] and "model" in headers[1]


def test_rows_without_group_render_flat() -> None:
    """catalog 面板没有族概念：不得凭空插标题行。"""

    lines = overlay.render_lines(_state())
    assert not any("──" in line for line in lines)


def test_non_tty_falls_back_to_numbered_choice(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """CI/管道里没有 alt-screen：必须还能选（编号），否则面板等于不可用。"""

    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "2")
    assert asyncio.run(overlay.run_async(_state())) == "beta"


def test_slash_opens_search_and_refines_the_choice(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """/ 进入搜索：读一个搜索词后重列编号，选中项必须来自过滤集。

    旧实现把 `__search__` 哨兵当选中 id 返回（随后被拼进斜杠命令）——本用例锁死
    这条路径：搜索必须真的过滤，选择必须真的生效。
    """

    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    answers = iter(["/", "bet", "1"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    assert asyncio.run(overlay.run_async(_state())) == "beta"


def test_search_matches_detail_text_in_the_numbered_fallback(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """编号回退同样吃中文搜索词（detail 列参与匹配）。"""

    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    answers = iter(["/", "第二", "1"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    assert asyncio.run(overlay.run_async(_state())) == "beta"


def test_empty_search_query_clears_the_filter(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """空搜索词 = 清掉过滤回到全表；连续两次搜索以最后一次为准。"""

    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    answers = iter(["/", "第二", "/", "", "3"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    assert asyncio.run(overlay.run_async(_state())) == "gamma"


def test_search_eof_keeps_the_previous_filter(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """搜索输入被 EOF 打断：保持既有过滤继续选，不得崩、不得清空。"""

    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    state = _state()
    overlay.set_query(state, "第二")

    def _input(prompt: str = "") -> str:
        if prompt == strings.PANEL_SEARCH_PROMPT:
            raise EOFError
        return "1"

    monkeypatch.setattr("builtins.input", _input)
    assert asyncio.run(overlay.run_async(state)) == "beta"


def test_non_tty_empty_input_cancels(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")
    assert asyncio.run(overlay.run_async(_state())) is None


def test_non_tty_out_of_range_cancels(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "9")
    assert asyncio.run(overlay.run_async(_state())) is None
