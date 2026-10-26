"""TUI 冒烟：Textual 无头驱动（`run_test`），验三条产品契约。

1. 打 `/` 立刻有候选（不依赖浮动菜单）；
2. 未知指令不发给模型；
3. 普通输入会被提交。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from questorharness.bootstrap.hosts.terminal import wire_view as view
from questorharness.bootstrap.hosts.tui.app import ApprovalScreen, QuestorApp, approval_head

COMMANDS = [
    {"name": "help", "description": "Show available commands", "aliases": [], "family": "session"},
    {"name": "model", "description": "Show or set the model", "aliases": [], "family": "model"},
]


def _host() -> tuple[SimpleNamespace, list[dict[str, Any]]]:
    posted: list[dict[str, Any]] = []

    async def request(
        method: str, path: str, body: bytes = b"", **_kw: object
    ) -> SimpleNamespace:
        if path.endswith("/commands"):
            payload = {"commands": COMMANDS}
            return SimpleNamespace(status=200, body=json.dumps(payload).encode(), headers={}, stream=None)
        if path.endswith("/profile"):
            payload = {"id": "coding", "name": "coding", "description": "local-first"}
            return SimpleNamespace(status=200, body=json.dumps(payload).encode(), headers={}, stream=None)
        if path.endswith("/events"):

            async def _empty():  # type: ignore[no-untyped-def]
                if False:  # pragma: no cover - 空流
                    yield b""

            return SimpleNamespace(status=200, body=b"", headers={}, stream=_empty())
        if "/catalog/" in path:
            return SimpleNamespace(status=200, body=b'{"items": []}', headers={}, stream=None)
        if path.endswith("/submit"):
            posted.append(json.loads(body))
            return SimpleNamespace(
                status=202, body=b'{"turnId":"t-1","state":"started"}', headers={}, stream=None
            )
        return SimpleNamespace(status=404, body=b"{}", headers={}, stream=None)

    return SimpleNamespace(transport=SimpleNamespace(request=request)), posted


def test_typing_slash_lists_candidates_immediately() -> None:
    host, _posted = _host()

    async def scenario() -> str:
        app = QuestorApp(host, profile_name="coding")  # type: ignore[arg-type]
        async with app.run_test() as pilot:
            await pilot.press("/")
            await pilot.pause()
            # Static 的内容取 `render()` 的结果（Textual 8 没有 `.renderable`）。
            return str(app.query_one("#hints").render())

    text = __import__("asyncio").run(scenario())
    assert "/help" in text and "/model" in text


def test_unknown_slash_command_is_not_submitted() -> None:
    host, posted = _host()

    async def scenario() -> None:
        app = QuestorApp(host, profile_name="coding")  # type: ignore[arg-type]
        async with app.run_test() as pilot:
            app.query_one("#prompt").value = "/nope"
            await pilot.press("enter")
            await pilot.pause()

    __import__("asyncio").run(scenario())
    assert posted == []


def test_plain_input_is_submitted() -> None:
    host, posted = _host()

    async def scenario() -> None:
        app = QuestorApp(host, profile_name="coding")  # type: ignore[arg-type]
        async with app.run_test() as pilot:
            app.query_one("#prompt").value = "你好"
            await pilot.press("enter")
            await pilot.pause()

    __import__("asyncio").run(scenario())
    assert posted and posted[0]["line"] == "你好"


def test_approval_head_is_one_short_line() -> None:
    """审批模态标题只占一行：长说明不能把框撑成整屏（实跑反馈“太大了”）。"""

    item = view.ApprovalItem(
        prompt_id="p-1",
        tool="agent",
        detail="",
        subject="Mutating tools require user confirmation in default mode. " * 4,
    )
    plain = approval_head(item).plain
    assert "\n" not in plain
    assert len(plain) <= 96
    assert "agent" in plain


def test_approval_modal_does_not_repeat_the_choices() -> None:
    """卡片自带的 `y 允许 · n 拒绝` 不得在模态里再出现一遍（旧截图里的重复行）。"""

    item = view.ApprovalItem(prompt_id="p-1", tool="bash", detail="", subject="ls")
    screen = ApprovalScreen(item)
    assert screen._item.tool == "bash"  # type: ignore[attr-defined]
    assert "y 允许" not in approval_head(item).plain


def test_tui_package_imports_without_starting_a_host() -> None:
    pytest.importorskip("textual")
    from questorharness.bootstrap.hosts.tui import QuestorApp as exported

    assert exported is QuestorApp
