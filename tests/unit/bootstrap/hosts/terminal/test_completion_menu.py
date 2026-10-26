"""`completion_menu.py`：Reasonix 风格补全菜单的纯逻辑（无 prompt_toolkit）。

移植自 `DeepSeek-Reasonix/internal/frontend/tui/complete.go`：
- wants_menu 决定何时自动弹（裸 `/cmd`、`@ref`）；
- move 环形移动选中项；
- accept_text 用选中项替换 token；
- should_accept_on_enter 复刻 "已打字=提交，否则=补全" 的 Enter 规则；
- visible_rows 是 8 行滑动窗口（选中项居中）。
"""

from __future__ import annotations

from questorharness.bootstrap.hosts.terminal import completion_menu as cm


def _menu(
    labels: list[str],
    *,
    start: int = 0,
    end: int = 0,
    kind: str = "slash",
    hint_of: dict[str, str] | None = None,
) -> cm.Menu:
    hint_of = hint_of or {}
    rows = [
        cm.MenuRow(label=label, insert=label, hint=hint_of.get(label, ""))
        for label in labels
    ]
    menu = cm.build(rows, start, end, kind=kind)
    assert menu is not None
    return menu


# ---- wants_menu -----------------------------------------------------------


def test_bare_slash_opens_the_menu() -> None:
    assert cm.wants_menu("/", 1) is True
    assert cm.wants_menu("/mo", 3) is True


def test_slash_with_an_argument_stops_the_menu() -> None:
    """`/model gpt` 已经不是纯 token，菜单不该再弹。"""
    assert cm.wants_menu("/model gpt", len("/model gpt")) is False


def test_at_token_opens_the_file_menu() -> None:
    text = "look at @sr"
    assert cm.wants_menu(text, len(text)) is True


def test_plain_text_does_not_open_the_menu() -> None:
    assert cm.wants_menu("hello", len("hello")) is False


def test_force_opens_on_a_bare_path_token() -> None:
    """Tab 是显式补全入口：裸路径也允许开（自动弹仍只认 `/` 与 `@`）。"""
    text = "not"
    assert cm.wants_menu(text, len(text), force=True) is True
    assert cm.wants_menu(text, len(text)) is False


# ---- build ----------------------------------------------------------------


def test_build_returns_none_without_rows() -> None:
    assert cm.build([], 0, 0) is None


def test_build_selects_the_first_row_and_keeps_order() -> None:
    menu = _menu(["/help", "/exit", "/clear"])
    assert [row.label for row in menu.rows] == ["/help", "/exit", "/clear"]
    assert menu.sel == 0
    assert menu.selected() is not None and menu.selected().label == "/help"


# ---- move -----------------------------------------------------------------


def test_move_wraps_around_in_both_directions() -> None:
    menu = _menu(["/a", "/b", "/c"])
    assert cm.move(menu, -1) == 2  # 从第一行往上 → 最后一行
    assert menu.sel == 2
    assert cm.move(menu, 1) == 0  # 从最后一行往下 → 第一行
    assert menu.sel == 0
    assert cm.move(menu, 1) == 1


def test_move_on_an_empty_menu_is_a_no_op() -> None:
    menu = cm.Menu(rows=[], start=0, end=0)
    assert cm.move(menu, 1) == 0
    assert menu.sel == 0


# ---- accept_text ----------------------------------------------------------


def test_accept_replaces_the_slash_token() -> None:
    menu = _menu(["/model", "/memory"], start=0, end=3)
    text, cursor = cm.accept_text(menu, "/mo")
    assert text == "/model"
    assert cursor == len("/model")


def test_accept_replaces_only_the_at_token() -> None:
    line = "see @sr"
    menu = _menu(["@src/"], start=4, end=len(line), kind="path")
    text, cursor = cm.accept_text(menu, line)
    assert text == "see @src/"
    assert cursor == len("see @src/")


# ---- should_accept_on_enter ----------------------------------------------


def test_enter_submits_when_the_line_already_equals_the_selection() -> None:
    menu = _menu(["/help", "/exit"])
    assert cm.should_accept_on_enter(menu, "/help") is False


def test_enter_accepts_when_the_line_is_only_a_prefix() -> None:
    menu = _menu(["/help", "/exit"])
    assert cm.should_accept_on_enter(menu, "/he") is True


# ---- visible_rows / menu_lines -------------------------------------------


def _many(n: int) -> cm.Menu:
    return _menu([f"/cmd{i:02d}" for i in range(n)])


def test_window_centers_the_selection_and_clamps_at_edges() -> None:
    menu = _many(20)

    menu.sel = 0
    first_window = [index for index, _ in cm.visible_rows(menu)]
    assert first_window == list(range(cm.VISIBLE_ROWS))

    menu.sel = 19
    last_window = [index for index, _ in cm.visible_rows(menu)]
    assert last_window == list(range(20 - cm.VISIBLE_ROWS, 20))

    menu.sel = 10
    mid_window = [index for index, _ in cm.visible_rows(menu)]
    assert mid_window == list(range(6, 6 + cm.VISIBLE_ROWS))


def test_menu_lines_marks_the_selected_row() -> None:
    menu = _many(3)
    lines = cm.menu_lines(menu, width=80)
    assert lines[0].startswith(cm.SELECT_MARKER)
    assert lines[1].startswith(cm.INDENT)
    assert "/cmd00" in lines[0]


def test_menu_lines_carries_the_hint_of_a_row() -> None:
    menu = _menu(
        ["/model"],
        hint_of={"/model": "Show or set the model"},
    )
    lines = cm.menu_lines(menu, width=80)
    assert "Show or set the model" in lines[0]


def test_menu_lines_appends_the_shortcut_hint_line() -> None:
    menu = _menu(["/help"])
    lines = cm.menu_lines(menu, width=80, hint="HINT-LINE")
    assert lines[-1] == "HINT-LINE"
