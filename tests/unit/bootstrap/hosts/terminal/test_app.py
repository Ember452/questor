"""`app.py`：提交裁决、哨兵读取、单次与交互两种驱动方式。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from questorharness.bootstrap.hosts.terminal import app as app_module


class _Transport:
    def __init__(self, *, status: int = 202, body: bytes = b"{}") -> None:
        self.status = status
        self.body = body
        self.calls: list[tuple[str, str]] = []

    async def request(self, method: str, path: str, **_kwargs: object) -> SimpleNamespace:
        self.calls.append((method, path))
        return SimpleNamespace(status=self.status, body=self.body, headers={}, stream=None)


def _host(transport: _Transport) -> SimpleNamespace:
    return SimpleNamespace(
        transport=transport,
        authority=SimpleNamespace(prompt_timeout=300.0),
    )


def _renderer() -> SimpleNamespace:
    return SimpleNamespace(
        note_queued=lambda: None,
        expect_turn=lambda: None,
        note_cancel_requested=lambda: None,
        busy=False,
        pending_turns=0,
        done=asyncio.Event(),
    )


def test_completion_catalog_maps_names_and_aliases() -> None:
    catalog = app_module.completion_catalog(
        [{"name": "compact", "description": "压缩", "aliases": ["cmp"]}]
    )
    assert catalog == {"/compact": "压缩", "/cmp": "压缩"}


def test_submit_reports_started_with_turn_id() -> None:
    transport = _Transport(body=b'{"turnId":"t-1","state":"started"}')
    result = asyncio.run(app_module.submit(_host(transport), "hello"))  # type: ignore[arg-type]
    assert result == app_module.SubmitResult(turn_id="t-1", state="started")
    assert transport.calls == [("POST", "/rt/r1/submit")]


def test_submit_reports_queued() -> None:
    transport = _Transport(status=202, body=b'{"turnId":"t-2","state":"queued"}')
    result = asyncio.run(app_module.submit(_host(transport), "again"))  # type: ignore[arg-type]
    assert result.state == "queued"


def test_submit_refusal_never_looks_like_success(capsys) -> None:  # type: ignore[no-untyped-def]
    """拒绝不走 stderr 裸 print（单一写终端出口），detail 随 SubmitResult 带回。"""
    transport = _Transport(status=409, body=b'{"code":"turn.busy","message":"busy"}')
    result = asyncio.run(app_module.submit(_host(transport), "x"))  # type: ignore[arg-type]
    assert result == app_module.SubmitResult(
        turn_id=None, state="refused", detail="turn.busy: busy"
    )
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_drive_turns_shows_refusal_through_the_renderer(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """交互模式被拒：经 renderer.show 给一行可见提示，然后继续读下一行。"""

    async def _one_line_then_eof(_session: object) -> str:
        if not getattr(_one_line_then_eof, "called", False):
            _one_line_then_eof.called = True  # type: ignore[attr-defined]
            return "x"
        return app_module.EOF

    transport = _Transport(status=409, body=b'{"code":"turn.busy","message":"busy"}')
    shown: list[str] = []
    renderer = _renderer()
    renderer.show = shown.append  # type: ignore[method-assign]
    monkeypatch.setattr(app_module, "read_line", _one_line_then_eof)

    result = asyncio.run(
        app_module.drive_turns(_host(transport), renderer, None, None)  # type: ignore[arg-type]
    )
    assert result == 0
    assert shown == ["  提交被拒（turn.busy: busy）"]


def test_read_line_returns_eof_and_interrupt_sentinels(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls = {"n": 0}

    def fake_input(_prompt: str = "") -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise KeyboardInterrupt
        raise EOFError

    monkeypatch.setattr("builtins.input", fake_input)
    assert asyncio.run(app_module.read_line(None)) == app_module.INTERRUPT
    assert asyncio.run(app_module.read_line(None)) == app_module.EOF


def test_single_prompt_mode_waits_for_turn_done() -> None:
    transport = _Transport(body=b'{"turnId":"t-1","state":"started"}')
    renderer = _renderer()

    async def scenario() -> int:
        task = asyncio.create_task(
            app_module.drive_turns(_host(transport), renderer, None, "hi")  # type: ignore[arg-type]
        )
        await asyncio.sleep(0.01)
        renderer.done.set()
        return await asyncio.wait_for(task, timeout=2)

    assert asyncio.run(scenario()) == 0


def test_eof_exits_without_submitting(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    transport = _Transport()
    renderer = _renderer()
    monkeypatch.setattr(app_module, "read_line", _eof)

    result = asyncio.run(
        app_module.drive_turns(_host(transport), renderer, None, None)  # type: ignore[arg-type]
    )
    assert result == 0
    assert transport.calls == []


async def _eof(_session: object) -> str:
    return app_module.EOF


def test_profile_info_feeds_the_footer_even_without_a_banner() -> None:
    """非交互（单次 prompt / 管道）也要拿到形态名，否则状态栏永远是 `？`。"""

    transport = _CommandTransport([])
    transport.body = b'{"id":"coding","name":"coding","description":"local-first"}'
    name, description = asyncio.run(app_module.profile_info(_host(transport)))  # type: ignore[arg-type]
    assert (name, description) == ("coding", "local-first")
    assert transport.calls == [("GET", "/rt/r1/profile")]


def test_profile_info_is_fail_soft() -> None:
    class _Boom(_CommandTransport):
        async def request(self, method: str, path: str, **_kwargs: object) -> SimpleNamespace:
            raise RuntimeError("down")

    assert asyncio.run(app_module.profile_info(_host(_Boom([])))) == ("?", "")  # type: ignore[arg-type]


class _CommandTransport:
    def __init__(self, commands: list[dict[str, object]]) -> None:
        import json

        self.body = json.dumps({"commands": commands}).encode("utf-8")
        self.calls: list[tuple[str, str]] = []

    async def request(self, method: str, path: str, **_kwargs: object) -> SimpleNamespace:
        self.calls.append((method, path))
        return SimpleNamespace(status=200, body=self.body, headers={}, stream=None)


def test_command_rows_come_from_the_registry_catalog() -> None:
    """:help 面板的行来自 /commands（与补全同源，禁硬编码清单）。"""

    transport = _CommandTransport(
        [{"name": "compact", "description": "压缩历史", "aliases": ["cmp"], "family": "session"}]
    )
    rows = asyncio.run(app_module.command_rows(_host(transport)))  # type: ignore[arg-type]
    assert rows == [
        {
            "id": "/compact",
            "label": "/compact  (/cmp)",
            "detail": "压缩历史",
            "group": "session",
        }
    ]
    assert transport.calls == [("GET", "/rt/r1/commands")]


def test_help_panel_is_read_only(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from questorharness.bootstrap.hosts.terminal import pickers

    transport = _CommandTransport([{"name": "help", "description": "列指令"}])
    renderer = SimpleNamespace(show=lambda _text: None)
    seen: list[list[dict[str, object]]] = []
    monkeypatch.setattr(
        pickers, "open_panel", lambda panel, items, **_kw: seen.append(list(items)) or "2"
    )

    assert (
        asyncio.run(
            app_module.open_panel(_host(transport), renderer, ":help")  # type: ignore[arg-type]
        )
        is None
    )
    assert seen and seen[0][0]["id"] == "/help"


def test_prompt_marker_has_a_single_source() -> None:
    """提示符唯一真源是 `strings.PROMPT`（Reasonix `❯ `）。

    `"> "` 字面量散落会漂出第二真源——`input_session.prompt_text` 曾经
    文档写 `❯ ` 实际返回 `> `，就是这种漂移的现场。
    """

    source = Path(app_module.__file__).read_text(encoding="utf-8")
    assert '"> "' not in source
    assert "strings.PROMPT" in source
