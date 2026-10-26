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


# ---- 补全菜单：选中/方向键/滚动/Tab/Enter（Reasonix 同款）----------------


def _host_with(commands: list[dict[str, Any]]) -> SimpleNamespace:
    async def request(
        method: str, path: str, body: bytes = b"", **_kw: object
    ) -> SimpleNamespace:
        if path.endswith("/commands"):
            return SimpleNamespace(
                status=200, body=json.dumps({"commands": commands}).encode(), headers={}, stream=None
            )
        if path.endswith("/profile"):
            return SimpleNamespace(status=200, body=b'{"name":"coding"}', headers={}, stream=None)
        if path.endswith("/events"):

            async def _empty():  # type: ignore[no-untyped-def]
                if False:  # pragma: no cover
                    yield b""

            return SimpleNamespace(status=200, body=b"", headers={}, stream=_empty())
        if "/catalog/" in path:
            return SimpleNamespace(status=200, body=b'{"items": []}', headers={}, stream=None)
        return SimpleNamespace(status=404, body=b"{}", headers={}, stream=None)

    return SimpleNamespace(transport=SimpleNamespace(request=request))


def _many_commands(n: int) -> list[dict[str, Any]]:
    return [
        {"name": f"cmd{i:02d}", "description": f"d{i}", "aliases": [], "family": "x"}
        for i in range(n)
    ]


def test_arrow_down_then_up_moves_the_selection() -> None:
    host = _host_with(COMMANDS)

    async def scenario() -> tuple[int, int]:
        app = QuestorApp(host, profile_name="coding")  # type: ignore[arg-type]
        async with app.run_test() as pilot:
            await pilot.press("/")
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()
            down = app._menu.sel if app._menu else -1
            await pilot.press("up")
            await pilot.pause()
            up = app._menu.sel if app._menu else -1
            return down, up

    down, up = __import__("asyncio").run(scenario())
    assert down == 1
    assert up == 0


def test_completion_window_scrolls_past_the_visible_rows() -> None:
    host = _host_with(_many_commands(12))

    async def scenario() -> tuple[int, str]:
        app = QuestorApp(host, profile_name="coding")  # type: ignore[arg-type]
        async with app.run_test() as pilot:
            await pilot.press("/")
            await pilot.pause()
            for _ in range(11):  # 从第 0 行一路到底（12 行 > 8 行窗口）
                await pilot.press("down")
                await pilot.pause()
            sel = app._menu.sel if app._menu else -1
            plain = str(app.query_one("#hints").render())
            return sel, plain

    sel, plain = __import__("asyncio").run(scenario())
    assert sel == 11
    assert "/cmd11" in plain
    assert "/cmd00" not in plain  # 窗口已滚走，证明能滚动


def test_tab_accepts_the_selected_completion() -> None:
    host = _host_with(COMMANDS)

    async def scenario() -> str:
        app = QuestorApp(host, profile_name="coding")  # type: ignore[arg-type]
        async with app.run_test() as pilot:
            for ch in "/he":
                await pilot.press(ch)
                await pilot.pause()
            await pilot.press("tab")
            await pilot.pause()
            return app.query_one("#prompt").value

    assert __import__("asyncio").run(scenario()) == "/help"


def test_enter_completes_a_prefix_then_submits_the_finished_command() -> None:
    host, posted = _host()

    async def scenario() -> tuple[str, list[str]]:
        app = QuestorApp(host, profile_name="coding")  # type: ignore[arg-type]
        async with app.run_test() as pilot:
            for ch in "/he":
                await pilot.press(ch)
                await pilot.pause()
            await pilot.press("enter")  # 前缀 → 先补全，不提交
            await pilot.pause()
            value = app.query_one("#prompt").value
            await pilot.press("enter")  # 已是整条命令 → 提交
            await pilot.pause()
            return value, [p["line"] for p in posted]

    value, lines = __import__("asyncio").run(scenario())
    assert value == "/help"
    assert lines == ["/help"]


# ---- Ctrl-C 两下退出 / 历史召回 / 面板可选中 ---------------------------------


def _skills_host() -> tuple[SimpleNamespace, list[dict[str, Any]]]:
    posted: list[dict[str, Any]] = []
    skills = [
        {"id": "lark-doc", "label": "/lark-doc", "detail": "docs"},
        {"id": "lark-im", "label": "/lark-im", "detail": "im"},
    ]
    cmds = [
        {"name": "lark-doc", "description": "docs", "aliases": [], "family": "skill"},
        {"name": "lark-im", "description": "im", "aliases": [], "family": "skill"},
    ]

    async def request(
        method: str, path: str, body: bytes = b"", **_kw: object
    ) -> SimpleNamespace:
        if path.endswith("/commands"):
            body_out = json.dumps({"commands": cmds}).encode()
        elif path.endswith("/profile"):
            body_out = b'{"name":"coding"}'
        elif path.endswith("/events"):

            async def _empty():  # type: ignore[no-untyped-def]
                if False:  # pragma: no cover
                    yield b""

            return SimpleNamespace(status=200, body=b"", headers={}, stream=_empty())
        elif path.endswith("/catalog/skills"):
            body_out = json.dumps({"items": skills}).encode()
        elif "/catalog/" in path:
            body_out = b'{"items": []}'
        elif path.endswith("/submit"):
            posted.append(json.loads(body))
            return SimpleNamespace(
                status=202, body=b'{"turnId":"t-1","state":"started"}', headers={}, stream=None
            )
        else:
            body_out = b"{}"
        return SimpleNamespace(status=200, body=body_out, headers={}, stream=None)

    return SimpleNamespace(transport=SimpleNamespace(request=request)), posted


def test_ctrl_c_twice_when_idle_exits() -> None:
    host, _posted = _host()

    async def scenario() -> int:
        app = QuestorApp(host, profile_name="coding")  # type: ignore[arg-type]
        exits = {"n": 0}
        app.exit = lambda *a, **k: exits.__setitem__("n", exits["n"] + 1)  # type: ignore[method-assign]
        async with app.run_test() as pilot:
            await pilot.press("ctrl+c")  # 空闲第一下：仅提示
            await pilot.pause()
            await pilot.press("ctrl+c")  # 第二下：退出
            await pilot.pause()
        return exits["n"]

    assert __import__("asyncio").run(scenario()) >= 1


def test_up_arrow_recalls_previous_submission() -> None:
    host, _posted = _host()

    async def scenario() -> str:
        app = QuestorApp(host, profile_name="coding")  # type: ignore[arg-type]
        async with app.run_test() as pilot:
            app.query_one("#prompt").value = "first"
            await pilot.press("enter")
            await pilot.pause()
            app.query_one("#prompt").value = "second"
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("up")
            await pilot.pause()
            return app.query_one("#prompt").value

    assert __import__("asyncio").run(scenario()) == "second"


def test_panel_arrow_down_then_enter_picks_the_second_item() -> None:
    host, posted = _skills_host()

    async def scenario() -> None:
        app = QuestorApp(host, profile_name="coding")  # type: ignore[arg-type]
        async with app.run_test() as pilot:
            app.query_one("#prompt").value = ":skills"
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("down")  # 高亮移到第二条
            await pilot.pause()
            await pilot.press("enter")  # 选中高亮行
            await pilot.pause()

    __import__("asyncio").run(scenario())
    assert posted and posted[0]["line"] == "/lark-im"


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
