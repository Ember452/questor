"""`overlay.py`：面板状态机与编号回退（alt-screen 只做同一份内容的另一种画法）。"""

from __future__ import annotations

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


def test_non_tty_falls_back_to_numbered_choice(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """CI/管道里没有 alt-screen：必须还能选（编号），否则面板等于不可用。"""

    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "2")
    assert overlay.run(_state()) == "beta"


def test_non_tty_empty_input_cancels(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")
    assert overlay.run(_state()) is None


def test_non_tty_out_of_range_cancels(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "9")
    assert overlay.run(_state()) is None
