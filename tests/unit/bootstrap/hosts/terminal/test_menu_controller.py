"""`menu_controller`：把补全器候选接进 Reasonix 菜单，并驱动 buffer。

控制器只做"取候选 → 建菜单 → 按语义改 buffer"，渲染细节仍在 `completion_menu`。
用假补全器 + 假 buffer 验证语义，不需要 TTY。
"""

from __future__ import annotations

from prompt_toolkit.completion import Completion

from questorharness.bootstrap.hosts.terminal import menu_controller


class _Buf:
    def __init__(self, text: str) -> None:
        self.text = text
        self.cursor_position = len(text)


class _Completer:
    def __init__(self, completions: list[Completion]) -> None:
        self._completions = completions

    def get_completions(self, document: object, complete_event: object) -> list[Completion]:
        del document, complete_event
        return list(self._completions)


def _controller(*texts: tuple[str, str, int, str]) -> menu_controller.MenuController:
    """texts = (insert, display_meta, start_position, display) 四元组。"""

    completions = [
        Completion(text, start_position=start, display=display, display_meta=meta)
        for text, meta, start, display in texts
    ]
    return menu_controller.MenuController(_Completer(completions))


def test_refresh_opens_the_menu_on_a_bare_slash() -> None:
    controller = _controller(("/help", "Show help", -2, "/help"))
    controller.refresh(_Buf("/h"))
    assert controller.active is True
    menu = controller.menu
    assert menu is not None
    assert menu.rows[0].label == "/help"
    assert menu.rows[0].hint == "Show help"
    assert (menu.start, menu.end) == (0, 2)


def test_refresh_closes_the_menu_outside_a_completion_context() -> None:
    controller = _controller(("/help", "Show help", -2, "/help"))
    controller.refresh(_Buf("hello"))
    assert controller.active is False


def test_move_moves_the_selection_and_reports_handled() -> None:
    controller = _controller(
        ("/a", "a", -1, "/a"), ("/b", "b", -1, "/b"), ("/c", "c", -1, "/c")
    )
    buffer = _Buf("/")
    controller.refresh(buffer)
    assert controller.move(buffer, 1) is True
    assert controller.menu is not None and controller.menu.sel == 1


def test_move_is_unhandled_when_the_menu_is_closed() -> None:
    controller = _controller()
    assert controller.move(_Buf("plain"), 1) is False


def test_accept_replaces_the_token_and_closes_the_menu() -> None:
    controller = _controller(("/model", "model", -3, "/model"), ("/memory", "mem", -3, "/memory"))
    buffer = _Buf("/mo")
    controller.refresh(buffer)
    assert controller.accept(buffer) is True
    assert buffer.text == "/model"
    assert buffer.cursor_position == len("/model")
    assert controller.active is False


def test_enter_submits_when_the_line_already_names_the_selection() -> None:
    controller = _controller(("/model", "model", -6, "/model"))
    buffer = _Buf("/model")
    controller.refresh(buffer)
    assert controller.should_accept_on_enter(buffer) is False


def test_enter_accepts_when_the_line_is_only_a_prefix() -> None:
    controller = _controller(("/model", "model", -3, "/model"))
    buffer = _Buf("/mo")
    controller.refresh(buffer)
    assert controller.should_accept_on_enter(buffer) is True


def test_close_clears_an_open_menu() -> None:
    controller = _controller(("/a", "a", -1, "/a"))
    buffer = _Buf("/")
    controller.refresh(buffer)
    assert controller.close(buffer) is True
    assert controller.active is False


def test_refresh_keeps_the_selection_by_label() -> None:
    controller = _controller(
        ("/help", "h", -1, "/help"),
        ("/exit", "e", -1, "/exit"),
        ("/model", "m", -1, "/model"),
    )
    buffer = _Buf("/")
    controller.refresh(buffer)
    controller.move(buffer, 2)
    assert controller.menu is not None and controller.menu.sel == 2
    controller.refresh(buffer)
    assert controller.menu is not None and controller.menu.sel == 2


def test_accepting_a_directory_keeps_the_menu_open_for_the_next_level() -> None:
    controller = _controller(("@src/", "dir", -2, "src/"))
    buffer = _Buf("@s")
    controller.refresh(buffer)
    assert controller.accept(buffer) is True
    assert buffer.text == "@src/"
    assert controller.active is True


def test_toolbar_is_empty_when_the_menu_is_closed() -> None:
    assert _controller().toolbar() == []


def test_toolbar_draws_the_reasonix_cursor_and_hint() -> None:
    from questorharness.bootstrap.hosts.terminal import strings

    controller = _controller(("/a", "desc-a", -1, "/a"))
    controller.refresh(_Buf("/"))
    text = "".join(piece for _, piece in controller.toolbar())
    assert "/a" in text
    assert "desc-a" in text
    assert strings.MENU_HINT_SLASH in text
