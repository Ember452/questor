"""`input_session` + 菜单接线：打字必须真的开/关菜单。

回归 `on_text_changed` 的 Event 用法——早期写成 `= menu.refresh` 覆盖了 Event 本体，
每次敲键都 `'function' object has no attribute 'fire'`，整个 REPL 直接崩。这个用例
在 headless（Dummy 输入/输出 + 运行中的事件循环）里把整条链跑通，钉死这个 bug。
"""

from __future__ import annotations

import asyncio
import sys

import pytest
from prompt_toolkit.input import DummyInput
from prompt_toolkit.output import DummyOutput

from questorharness.bootstrap.hosts.terminal import input_session, keymap, menu_controller

CATALOG = {"/help": "Show help", "/exit": "Exit", "/model": "Show or set the model"}


@pytest.fixture()
def headless(monkeypatch: pytest.MonkeyPatch) -> None:
    import prompt_toolkit.input.defaults as in_defaults
    import prompt_toolkit.output.defaults as out_defaults

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(out_defaults, "create_output", lambda *a, **k: DummyOutput())
    monkeypatch.setattr(in_defaults, "create_input", lambda *a, **k: DummyInput())


def test_typing_opens_and_closes_the_menu(headless: None) -> None:  # type: ignore[no-untyped-def]
    async def scenario() -> tuple[bool, list[str], bool, bool]:
        menu = menu_controller.MenuController()
        session = input_session.build(CATALOG, key_bindings=keymap.build(menu), menu=menu)
        assert session is not None
        buffer = session.default_buffer
        # 模拟真实打字：insert_text 会把光标推到字符之后（直接赋 text 会把光标留在 0）。
        buffer.insert_text("/")
        opened = menu.active
        labels = [row.label for row in (menu.menu.rows if menu.menu else [])]
        toolbar_shown = session.bottom_toolbar is not None
        buffer.text = ""
        buffer.insert_text("hello")
        return opened, labels, toolbar_shown, menu.active

    opened, labels, toolbar_shown, closed = asyncio.run(scenario())
    assert opened is True
    assert labels[:2] == ["/help", "/exit"]
    assert toolbar_shown is True
    assert closed is False
