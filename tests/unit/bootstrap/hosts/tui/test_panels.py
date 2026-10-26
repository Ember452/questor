"""`:` 面板：候选来源、搜索过滤、选中后回命令（Textual 无头驱动）。"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

from questorharness.bootstrap.hosts.tui.app import QuestorApp
from questorharness.bootstrap.hosts.tui.panels import PanelScreen

COMMANDS = [
    {"name": "help", "description": "Show available commands", "aliases": [], "family": "session"},
    {"name": "model", "description": "Show or set the model", "aliases": [], "family": "model"},
]

CATALOG = [
    {"id": "glm-4.7", "label": "glm-4.7", "detail": "zhipu"},
    {"id": "deepseek-flash", "label": "deepseek-flash", "detail": "deepseek"},
]


def _host(catalog: list[dict[str, Any]] | None = None) -> tuple[SimpleNamespace, list[dict[str, Any]]]:
    posted: list[dict[str, Any]] = []

    async def request(
        method: str, path: str, body: bytes = b"", **_kw: object
    ) -> SimpleNamespace:
        if path.endswith("/commands"):
            payload: Any = {"commands": COMMANDS}
            return SimpleNamespace(status=200, body=json.dumps(payload).encode(), headers={}, stream=None)
        if path.endswith("/profile"):
            payload = {"id": "coding", "name": "coding", "description": "local-first"}
            return SimpleNamespace(status=200, body=json.dumps(payload).encode(), headers={}, stream=None)
        if path.endswith("/history"):
            payload = {"sessionId": "s", "messages": []}
            return SimpleNamespace(status=200, body=json.dumps(payload).encode(), headers={}, stream=None)
        if "/catalog/" in path:
            payload = {"items": catalog or []}
            return SimpleNamespace(status=200, body=json.dumps(payload).encode(), headers={}, stream=None)
        if path.endswith("/submit"):
            posted.append(json.loads(body))
            return SimpleNamespace(
                status=202, body=b'{"turnId":"t-1","state":"started"}', headers={}, stream=None
            )
        if path.endswith("/events"):
            async def _empty():  # type: ignore[no-untyped-def]
                if False:  # pragma: no cover
                    yield b""

            return SimpleNamespace(status=200, body=b"", headers={}, stream=_empty())
        return SimpleNamespace(status=404, body=b"{}", headers={}, stream=None)

    return SimpleNamespace(transport=SimpleNamespace(request=request)), posted


def test_colon_panel_lists_the_catalog_and_submits_the_choice() -> None:
    """打 `:model` → 面板 → 选中 → 提交 `/model <id>`（与行式 REPL 同一命令模板）。"""

    host, posted = _host(CATALOG)

    async def scenario() -> type[PanelScreen] | None:
        app = QuestorApp(host, profile_name="coding")  # type: ignore[arg-type]
        async with app.run_test() as pilot:
            app.query_one("#prompt").value = ":model"
            await pilot.press("enter")
            await pilot.pause()
            opened = type(app.screen) if isinstance(app.screen, PanelScreen) else None
            await pilot.press("enter")  # 选中高亮的第一项
            # 选中后的提交在 worker 里跑：等它真的把 POST 发出去（最多 1s）。
            for _ in range(40):
                await pilot.pause()
                await asyncio.sleep(0.025)
                if posted:
                    break
            return opened

    opened = asyncio.run(scenario())
    assert opened is PanelScreen
    assert posted and posted[0]["line"] == "/model glm-4.7"


def test_colon_panel_reports_an_empty_catalog_instead_of_opening() -> None:
    """空面板给一行提示就结束，不能弹出一个没有内容的框。"""

    host, posted = _host([])

    async def scenario() -> bool:
        app = QuestorApp(host, profile_name="coding")  # type: ignore[arg-type]
        async with app.run_test() as pilot:
            app.query_one("#prompt").value = ":model"
            await pilot.press("enter")
            await pilot.pause()
            return isinstance(app.screen, PanelScreen)

    assert asyncio.run(scenario()) is False
    assert posted == []


def test_unknown_colon_alias_prints_the_panel_list() -> None:
    host, posted = _host(CATALOG)

    async def scenario() -> None:
        app = QuestorApp(host, profile_name="coding")  # type: ignore[arg-type]
        async with app.run_test() as pilot:
            app.query_one("#prompt").value = ":nope"
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(scenario())
    assert posted == []
