"""`app.py`：提交裁决、哨兵读取、单次与交互两种驱动方式。"""

from __future__ import annotations

import asyncio
import json
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
        # 新增的模态契约：drive_turns 先问有没有待答审批，再决定这一行是不是新消息。
        has_pending_prompt=False,
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

    async def _fake_open(panel: object, items: list[dict[str, object]], **_kw: object) -> str:
        seen.append(list(items))
        return "2"

    monkeypatch.setattr(pickers, "open_panel", _fake_open)

    assert (
        asyncio.run(
            app_module.open_panel(_host(transport), renderer, ":help")  # type: ignore[arg-type]
        )
        is None
    )
    assert seen and seen[0][0]["id"] == "/help"


def test_unknown_command_name_only_flags_unregistered_slash_input() -> None:
    catalog = {"/help": "", "/model": ""}
    assert app_module.unknown_command_name("/nope", catalog) == "/nope"
    assert app_module.unknown_command_name("/model gpt", catalog) is None
    assert app_module.unknown_command_name("hello", catalog) is None
    # 目录取数失败（空）时不得把所有斜杠命令都判死。
    assert app_module.unknown_command_name("/nope", {}) is None


def test_unknown_slash_command_is_never_sent_to_the_model(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """实跑事故：打 `/` 想找指令，整句被当 prompt 发给模型，模型开始跑 bash。"""

    async def _line(_session: object) -> str:
        if not getattr(_line, "called", False):
            _line.called = True  # type: ignore[attr-defined]
            return "/nope"
        return app_module.EOF

    async def _no_panel(*_args: object, **_kwargs: object) -> None:
        return None

    transport = _Transport()
    renderer = _renderer()
    shown: list[str] = []
    renderer.show = shown.append  # type: ignore[method-assign]
    monkeypatch.setattr(app_module, "read_line", _line)
    monkeypatch.setattr(app_module, "open_panel", _no_panel)

    result = asyncio.run(
        app_module.drive_turns(_host(transport), renderer, None, None, {"/help": ""})  # type: ignore[arg-type]
    )
    assert result == 0
    assert transport.calls == []  # 没有 POST /submit
    assert shown and "未知指令" in shown[0]


def test_panel_items_share_one_source_between_hosts() -> None:
    """面板取数真源：transcript→/history，help→/commands，其余→/catalog/<kind>。"""

    from questorharness.bootstrap.hosts.terminal import pickers

    requested: list[str] = []

    async def request(method: str, path: str, body: bytes = b"", **_kw: object) -> SimpleNamespace:
        requested.append(path)
        if path.endswith("/history"):
            payload = {"messages": [{"role": "user", "blocks": [{"type": "text", "text": "问题"}]}]}
        elif path.endswith("/commands"):
            payload = {"commands": [{"name": "help", "description": "d", "aliases": [], "family": "session"}]}
        else:
            payload = {"items": [{"id": "glm"}]}
        return SimpleNamespace(status=200, body=json.dumps(payload).encode(), headers={}, stream=None)

    host = SimpleNamespace(transport=SimpleNamespace(request=request))

    transcript = asyncio.run(app_module.panel_items(host, pickers.PANELS["transcript"]))  # type: ignore[arg-type]
    help_rows = asyncio.run(app_module.panel_items(host, pickers.PANELS["help"]))  # type: ignore[arg-type]
    models = asyncio.run(app_module.panel_items(host, pickers.PANELS["models"]))  # type: ignore[arg-type]

    assert transcript and transcript[0]["detail"] == "问题"
    assert help_rows and help_rows[0]["id"] == "/help"
    assert models == [{"id": "glm"}]
    assert requested == ["/rt/r1/history", "/rt/r1/commands", "/rt/r1/catalog/models"]


def test_panel_items_raises_when_the_catalog_refuses() -> None:
    """取数失败要抛（由调用方决定提示），不能静默返回空表。"""

    from questorharness.bootstrap.hosts.terminal import pickers

    async def request(method: str, path: str, body: bytes = b"", **_kw: object) -> SimpleNamespace:
        return SimpleNamespace(status=404, body=b'{"code":"catalog.unknown"}', headers={}, stream=None)

    host = SimpleNamespace(transport=SimpleNamespace(request=request))

    try:
        asyncio.run(app_module.panel_items(host, pickers.PANELS["models"]))  # type: ignore[arg-type]
    except RuntimeError as exc:
        assert "catalog.unknown" in str(exc)
    else:  # pragma: no cover - 没有抛就是错
        raise AssertionError("panel_items 必须抛出取数失败")


def test_prompt_marker_has_a_single_source() -> None:
    """提示符唯一真源是 `strings.prompt_marker()`（Reasonix `❯ `，装不下则 `> `）。

    `"> "` 字面量散落会漂出第二真源——`input_session.prompt_text` 曾经
    文档写 `❯ ` 实际返回 `> `，就是这种漂移的现场；直接引 `strings.PROMPT`
    则会在 cp936 控制台上抛 UnicodeEncodeError，同样禁用。
    """

    source = Path(app_module.__file__).read_text(encoding="utf-8")
    assert '"> "' not in source
    assert "strings.PROMPT\n" not in source
    assert "strings.PROMPT)" not in source
    assert "strings.prompt_marker()" in source
