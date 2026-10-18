"""P9 T6c/T7 集成：鉴权外部 OpenAI lane 端到端（ASGITransport，脚本化 provider）。

覆盖 DoD：① 外部客户端 stream/非 stream 调用；② API-key fail-closed（无/错 key→401）；
③ 非文本 part 归一拒绝（400、不起 run）；⑧ 投影只增不破（[DONE] 终结）。诚实：真广网部署/TLS 属算子侧。
"""

from __future__ import annotations

from pathlib import Path

import httpx

from questor.contracts.events import Envelope, EventType
from questor.contracts.ports import StreamChunk
from questor.providers.fake import ScriptedProvider
from questor.providers.store_sqlite import SQLiteStore
from questor.surfaces.cli import CliSurface
from questor.surfaces.http_sse import EventServer, create_app
from questor.surfaces.openai_compat import _stream_with_cancel

_AUTH = {"Authorization": "Bearer sk-test"}


async def _make_client(tmp_path: Path) -> tuple[SQLiteStore, httpx.AsyncClient]:
    store = await SQLiteStore(str(tmp_path / "db.sqlite")).connect()
    provider = ScriptedProvider([[StreamChunk(kind="text", text="hi "), StreamChunk(kind="finish", finish_reason="stop")]])
    surface = CliSurface(workspace_root=tmp_path, store=store, provider=provider)
    server = EventServer(surface, store)
    app = create_app(server, openai_api_keys=["sk-test"])
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://svc", timeout=30, trust_env=False)
    return store, client


async def test_openai_auth_fail_closed(tmp_path: Path) -> None:
    store, client = await _make_client(tmp_path)
    try:
        body = {"messages": [{"role": "user", "content": "x"}]}
        r = await client.post("/v1/chat/completions", json=body)  # 无 key
        assert r.status_code == 401
        r = await client.post("/v1/chat/completions", headers={"Authorization": "Bearer wrong"}, json=body)  # 错 key
        assert r.status_code == 401
    finally:
        await client.aclose()
        await store.close()


async def test_openai_non_text_rejected_no_run(tmp_path: Path) -> None:
    store, client = await _make_client(tmp_path)
    try:
        r = await client.post(
            "/v1/chat/completions",
            headers=_AUTH,
            json={"messages": [{"role": "user", "content": [{"type": "text", "text": "look"}, {"type": "image_url", "image_url": {"url": "u"}}]}]},
        )
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "unsupported_modality"
        # MI-3：拒必须“不起 run”——store 无任何未完成 run（start_run 未被调）。
        assert await store.list_unfinished_runs() == ()
    finally:
        await client.aclose()
        await store.close()


async def test_openai_non_stream_aggregates_final_text(tmp_path: Path) -> None:
    store, client = await _make_client(tmp_path)
    try:
        r = await client.post("/v1/chat/completions", headers=_AUTH, json={"messages": [{"role": "user", "content": "hello"}]})
        assert r.status_code == 200
        data = r.json()
        assert data["object"] == "chat.completion"
        assert "hi" in data["choices"][0]["message"]["content"]
        assert data["choices"][0]["finish_reason"] == "stop"
    finally:
        await client.aclose()
        await store.close()


async def test_openai_stream_ends_with_done(tmp_path: Path) -> None:
    store, client = await _make_client(tmp_path)
    try:
        async with client.stream(
            "POST", "/v1/chat/completions", headers=_AUTH, json={"messages": [{"role": "user", "content": "hello"}], "stream": True}
        ) as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")
            text = "".join([chunk async for chunk in resp.aiter_text()])
        assert "[DONE]" in text
        assert "chat.completion.chunk" in text
    finally:
        await client.aclose()
        await store.close()


# —— 断连即取消：不依赖 HTTP 拆除时机，直接驱动投影生成器并在未达终态时 aclose —— #
class _StubBus:
    def __init__(self, envelopes: list[Envelope]) -> None:
        self._envelopes = envelopes

    def subscribe(self, run_id: str, after_seq: int = 0, *, expected_version: int | None = None):
        async def _gen():
            for env in self._envelopes:
                yield env

        return _gen()


class _StubServer:
    def __init__(self, envelopes: list[Envelope]) -> None:
        self.cancelled: list[str] = []
        self.bus = _StubBus(envelopes)

    async def cancel(self, run_id: str) -> None:
        self.cancelled.append(run_id)


async def test_disconnect_cancels_run_via_inbox() -> None:
    # 事件流未到终态（无 run_completed/cancelled/failed）→ 客户端断开（aclose）应经 inbox 提 Cancel。
    envs = [
        Envelope(v=1, seq=1, run_id="r1", type=EventType.RUN_STARTED, data={"run_id": "r1"}),
        Envelope(v=1, seq=2, run_id="r1", type=EventType.TEXT_DELTA, data={"delta": "partial"}),
    ]
    server = _StubServer(envs)
    agen = _stream_with_cancel(server, "r1", "chatcmpl-1", "questor", 123)
    await agen.__anext__()  # 拿到首帧（role delta）
    await agen.aclose()  # 模拟客户端断连（未达终态）
    assert server.cancelled == ["r1"]


async def test_openai_non_ascii_content_roundtrip(tmp_path: Path) -> None:
    """MI-1（plan §6 钉宿）：非 ASCII/emoji 内容经 `ensure_ascii=False` + utf-8 往返不崩。"""
    store = await SQLiteStore(str(tmp_path / "na.db")).connect()
    try:
        provider = ScriptedProvider([[StreamChunk(kind="text", text="héllo 世界 \U0001f30d"), StreamChunk(kind="finish", finish_reason="stop")]])
        surface = CliSurface(workspace_root=tmp_path, store=store, provider=provider)
        server = EventServer(surface, store)
        app = create_app(server, openai_api_keys=["sk-test"])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://s", timeout=30, trust_env=False) as client:
            r = await client.post("/v1/chat/completions", headers=_AUTH, json={"messages": [{"role": "user", "content": "hi"}]})
        assert r.status_code == 200
        content = r.json()["choices"][0]["message"]["content"]
        assert "h\u00e9llo" in content and "世界" in content and "\U0001f30d" in content, content
    finally:
        await store.close()
