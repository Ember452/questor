"""`--resume` 回放：纯函数形状 + 真 App 里挂进对话区。"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

from questorharness.bootstrap.hosts.terminal import strings
from questorharness.bootstrap.hosts.tui.app import QuestorApp
from questorharness.bootstrap.hosts.tui.replay import history_renderables, message_text

HISTORY = [
    {"role": "user", "blocks": [{"type": "text", "text": "上次的问题"}]},
    {
        "role": "assistant",
        "blocks": [
            {"type": "tool_use", "id": "c1", "name": "bash"},
            {"type": "text", "text": "上次的回答"},
        ],
    },
    {"role": "user", "blocks": [{"type": "tool_result", "content": "no text", "isError": False}]},
]


def test_message_text_joins_text_blocks_and_ignores_tools() -> None:
    assert message_text(HISTORY[1]) == "上次的回答"
    assert message_text(HISTORY[2]) == ""
    assert message_text({"role": "user"}) == ""


def test_history_renderables_keeps_user_and_assistant_text() -> None:
    rows = history_renderables(HISTORY)
    plain = [getattr(row, "plain", str(row)) for row in rows]
    assert any("上次的问题" in str(item) for item in plain)
    assert len(rows) == 2  # 第三条（只有 tool_result）被跳过


def _host() -> SimpleNamespace:
    async def request(
        method: str, path: str, body: bytes = b"", **_kw: object
    ) -> SimpleNamespace:
        if path.endswith("/commands"):
            payload: Any = {"commands": []}
            return SimpleNamespace(status=200, body=json.dumps(payload).encode(), headers={}, stream=None)
        if path.endswith("/profile"):
            payload = {"id": "coding", "name": "coding", "description": "local-first"}
            return SimpleNamespace(status=200, body=json.dumps(payload).encode(), headers={}, stream=None)
        if path.endswith("/history"):
            payload = {"sessionId": "s", "messages": HISTORY}
            return SimpleNamespace(status=200, body=json.dumps(payload).encode(), headers={}, stream=None)
        if "/catalog/" in path:
            return SimpleNamespace(status=200, body=b'{"items": []}', headers={}, stream=None)
        if path.endswith("/events"):
            async def _empty():  # type: ignore[no-untyped-def]
                if False:  # pragma: no cover
                    yield b""

            return SimpleNamespace(status=200, body=b"", headers={}, stream=_empty())
        return SimpleNamespace(status=404, body=b"{}", headers={}, stream=None)

    return SimpleNamespace(transport=SimpleNamespace(request=request))


def test_resume_replays_history_into_the_conversation() -> None:
    """`--resume` 启动时把上次会话挂进对话区，并明确告知恢复了几块。"""

    host = _host()

    async def scenario() -> list[str]:
        app = QuestorApp(host, profile_name="coding", replay=True)  # type: ignore[arg-type]
        async with app.run_test() as pilot:
            await pilot.pause()
            return [str(widget.render()) for widget in app.query("#conversation > *")]

    rendered = asyncio.run(scenario())
    joined = "\n".join(rendered)
    assert "上次的问题" in joined
    assert strings.REPLAY_LEAD.split("（")[0].strip() in joined


def test_without_resume_the_conversation_stays_empty() -> None:
    host = _host()

    async def scenario() -> str:
        app = QuestorApp(host, profile_name="coding")  # type: ignore[arg-type]
        async with app.run_test() as pilot:
            await pilot.pause()
            return "\n".join(str(widget.render()) for widget in app.query("#conversation > *"))

    assert "上次的问题" not in asyncio.run(scenario())
