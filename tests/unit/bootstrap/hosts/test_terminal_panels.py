"""`:kind` 面板入口：拉 catalog → 选中 → 回到正常提交链。"""

from __future__ import annotations

import asyncio
import io
import json
from types import SimpleNamespace

from rich.console import Console

from questorharness.bootstrap.hosts import terminal_client
from questorharness.bootstrap.hosts.serve.authority import Authority
from questorharness.bootstrap.hosts.serve.broadcaster import Broadcaster
from questorharness.bootstrap.hosts.serve.wire import WireEncoder
from questorharness.bootstrap.hosts.terminal import pickers, strings


class _CatalogHost:
    """只需要 transport 面：catalog 返回固定行，选中项回写成命令。"""

    def __init__(self, items: list[dict[str, object]]) -> None:
        self.items = items
        self.requested: list[str] = []

        async def handler(_method: str, path: str, **_kwargs: object) -> SimpleNamespace:
            self.requested.append(path)
            body = json.dumps({"kind": "models", "items": self.items}).encode("utf-8")
            return SimpleNamespace(status=200, body=body, headers={}, stream=None)

        self.transport = SimpleNamespace(request=handler)
        self.authority = Authority()
        self.broadcaster = Broadcaster()
        self.encoder = WireEncoder()
        self.runtime = SimpleNamespace(cwd=".", session_id="sid")


def _renderer(
    buffer: io.StringIO, items: list[dict[str, object]] | None = None
) -> tuple[terminal_client.TerminalRenderer, _CatalogHost]:
    """面板测试宿主：默认一行可用数据，传 `[]` 则空目录。"""

    host = _CatalogHost(
        [{"id": "work", "label": "work", "detail": "deepseek · deepseek-v4", "current": True}]
        if items is None
        else items
    )
    return (
        terminal_client.TerminalRenderer(host, Console(file=buffer, force_terminal=False)),
        host,
    )


def test_model_panel_selection_becomes_a_slash_command(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    buffer = io.StringIO()
    renderer, host = _renderer(buffer)
    monkeypatch.setattr(
        pickers, "open_panel", lambda panel, items, **_kw: str(items[0]["id"])
    )

    line = asyncio.run(terminal_client._open_panel(host, renderer, ":model"))

    assert line == "/model work"
    assert host.requested == ["/rt/r1/catalog/models"]


def test_unknown_alias_shows_the_available_panels_without_requesting(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    buffer = io.StringIO()
    renderer, host = _renderer(buffer)

    assert asyncio.run(terminal_client._open_panel(host, renderer, ":nope")) is None
    assert host.requested == []
    assert pickers.list_hint() in buffer.getvalue()


def test_empty_catalog_renders_an_empty_state(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    buffer = io.StringIO()
    renderer, host = _renderer(buffer, [])
    called = {"pick": False}

    def _never(*_args: object, **_kwargs: object) -> None:
        called["pick"] = True
        return None

    monkeypatch.setattr(pickers, "open_panel", _never)

    assert asyncio.run(terminal_client._open_panel(host, renderer, ":model")) is None
    assert strings.PANEL_EMPTY in buffer.getvalue()
    assert called["pick"] is False


def test_unavailable_catalog_does_not_open_a_panel(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    buffer = io.StringIO()
    renderer, host = _renderer(buffer, [])

    async def boom(_method: str, _path: str, **_kwargs: object) -> SimpleNamespace:
        raise RuntimeError("connection closed")

    host.transport.request = boom  # type: ignore[attr-defined]
    monkeypatch.setattr(pickers, "open_panel", lambda *a, **k: "work")

    assert asyncio.run(terminal_client._open_panel(host, renderer, ":model")) is None
    assert "面板取不到数据" in buffer.getvalue()
