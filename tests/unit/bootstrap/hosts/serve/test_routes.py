"""路由层单测：状态码、拒绝码矩阵与 SSE 首帧。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from questorharness.bootstrap.hosts.serve.authority import Authority, TurnRecord
from questorharness.bootstrap.hosts.serve.broadcaster import Broadcaster
from questorharness.bootstrap.hosts.serve.routes import Router
from questorharness.bootstrap.hosts.serve.transport import MemoryTransport
from questorharness.bootstrap.hosts.serve.wire import WireEncoder

PROFILE_YAML = """
name: coding
description: test profile
is_default: true
ui:
  capabilities:
    chat: ready
    inspector: absent
"""


class FakeHost:
    """只实现路由需要的宿主面。"""

    def __init__(self, tmp_path: Path) -> None:
        (tmp_path / "coding.yaml").write_text(PROFILE_YAML, encoding="utf-8")
        self.runtime = type("Runtime", (), {"cwd": str(tmp_path), "session_id": "sid"})()
        self.authority = Authority()
        self.broadcaster = Broadcaster()
        self.encoder = WireEncoder()
        self.profile_root = tmp_path
        self.profile_id = "coding"
        self.started: list[TurnRecord] = []
        self.cancelled: list[str] = []

    def start_turn_task(self, record: TurnRecord) -> None:
        """记录而不真正跑回合。"""
        self.started.append(record)

    def cancel_turn(self, turn_id: str, client_id: str) -> bool:
        """只在持有者且记录存在时成功。"""
        if not self.authority.is_owner(turn_id, client_id):
            return False
        self.cancelled.append(turn_id)
        return True


def _transport(tmp_path: Path) -> tuple[MemoryTransport, FakeHost]:
    """构造 memory transport 与假宿主。"""
    host = FakeHost(tmp_path)
    return MemoryTransport(Router(host)), host


def _json(response) -> dict:  # type: ignore[no-untyped-def]
    return json.loads(response.body)


def test_submit_started_then_queued_then_busy(tmp_path: Path) -> None:
    """提交矩阵：202 started → 202 queued → 409 busy。"""

    async def scenario() -> None:
        transport, host = _transport(tmp_path)
        first = await transport.request(
            "POST",
            "/rt/r1/submit",
            body=json.dumps({"line": "hi", "clientRequestId": "r1"}).encode(),
        )
        assert first.status == 202
        assert _json(first)["state"] == "started"
        assert len(host.started) == 1
        second = await transport.request(
            "POST",
            "/rt/r1/submit",
            body=json.dumps({"line": "again", "clientRequestId": "r2"}).encode(),
            client_id="other",
        )
        assert second.status == 202
        assert _json(second)["state"] == "queued"
        third = await transport.request(
            "POST",
            "/rt/r1/submit",
            body=json.dumps({"line": "third", "clientRequestId": "r3"}).encode(),
        )
        assert third.status == 409
        assert _json(third)["code"] == "turn.busy"

    asyncio.run(scenario())


def test_replay_request_id_returns_same_turn(tmp_path: Path) -> None:
    """幂等：同 id 返回同一 turnId，且不新建任务。"""

    async def scenario() -> None:
        transport, host = _transport(tmp_path)
        payload = json.dumps({"line": "hi", "clientRequestId": "same"}).encode()
        first = await transport.request("POST", "/rt/r1/submit", body=payload)
        again = await transport.request("POST", "/rt/r1/submit", body=payload)
        assert _json(first)["turnId"] == _json(again)["turnId"]
        assert len(host.started) == 1

    asyncio.run(scenario())


def test_submit_validation_is_400(tmp_path: Path) -> None:
    """缺字段/空体一律 400 + submit.invalid。"""

    async def scenario() -> None:
        transport, _ = _transport(tmp_path)
        empty = await transport.request("POST", "/rt/r1/submit", body=b"")
        assert empty.status == 400
        assert _json(empty)["code"] == "submit.invalid"
        no_id = await transport.request(
            "POST", "/rt/r1/submit", body=json.dumps({"line": "hi"}).encode()
        )
        assert no_id.status == 400

    asyncio.run(scenario())


def test_cancel_requires_owner(tmp_path: Path) -> None:
    """非持有者取消 → 409 turn.not_owner。"""

    async def scenario() -> None:
        transport, host = _transport(tmp_path)
        await transport.request(
            "POST",
            "/rt/r1/submit",
            body=json.dumps({"line": "hi", "clientRequestId": "r1"}).encode(),
            client_id="owner",
        )
        denied = await transport.request("POST", "/rt/r1/cancel", client_id="intruder")
        assert denied.status == 409
        assert _json(denied)["code"] == "turn.not_owner"
        allowed = await transport.request("POST", "/rt/r1/cancel", client_id="owner")
        assert allowed.status == 200
        assert host.cancelled

    asyncio.run(scenario())


def test_profile_reports_capabilities_and_unknown_is_404(tmp_path: Path) -> None:
    """能力位端点直读 bundle。"""

    async def scenario() -> None:
        transport, _ = _transport(tmp_path)
        ok = await transport.request("GET", "/rt/r1/profile")
        assert ok.status == 200
        assert _json(ok)["ui"]["capabilities"] == {"chat": "ready", "inspector": "absent"}
        missing = await transport.request("GET", "/rt/r1/profile", query={"id": "nope"})
        assert missing.status == 404
        assert _json(missing)["code"] == "profile.unknown"

    asyncio.run(scenario())


def test_history_without_snapshot_is_empty(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """无快照时返回空列表而不是报错。"""
    from questorharness.platform import session_storage

    monkeypatch.setattr(session_storage, "get_sessions_dir", lambda: tmp_path)

    async def scenario() -> None:
        transport, _ = _transport(tmp_path)
        response = await transport.request("GET", "/rt/r1/history")
        assert response.status == 200
        assert _json(response)["messages"] == []

    asyncio.run(scenario())


def test_events_first_frame_is_replay_gap_when_window_lost(tmp_path: Path) -> None:
    """越界重放先发 stream_reset 帧。"""

    async def scenario() -> None:
        transport, host = _transport(tmp_path)
        for index in range(5):
            await host.broadcaster.publish({"kind": "text", "text": str(index)})
        response = await transport.request("GET", "/rt/r1/events", last_event_id="99")
        assert response.stream is not None
        first = await response.stream.__anext__()
        assert b"stream_reset" in first
        assert b"replay_gap" in first

    asyncio.run(scenario())


def test_replay_of_queued_request_reports_queued(tmp_path: Path) -> None:
    """幂等重放不得谎报状态：排队中的请求重放回 queued。"""

    async def scenario() -> None:
        transport, _ = _transport(tmp_path)
        await transport.request(
            "POST",
            "/rt/r1/submit",
            body=json.dumps({"line": "one", "clientRequestId": "r1"}).encode(),
        )
        queued = await transport.request(
            "POST",
            "/rt/r1/submit",
            body=json.dumps({"line": "two", "clientRequestId": "r2"}).encode(),
        )
        assert _json(queued)["state"] == "queued"
        replay = await transport.request(
            "POST",
            "/rt/r1/submit",
            body=json.dumps({"line": "two", "clientRequestId": "r2"}).encode(),
        )
        assert _json(replay)["state"] == "queued"
        assert _json(replay)["turnId"] == _json(queued)["turnId"]

    asyncio.run(scenario())


def test_submit_records_transport_via(tmp_path: Path) -> None:
    """via 来自传输层：进程内是 cli，显式传 studio 才是 studio。"""

    async def scenario() -> None:
        transport, host = _transport(tmp_path)
        await transport.request(
            "POST",
            "/rt/r1/submit",
            body=json.dumps({"line": "hi", "clientRequestId": "r1"}).encode(),
        )
        assert host.started[0].via == "cli"
        host.authority.finish(host.started[0].turn_id)
        await transport.request(
            "POST",
            "/rt/r1/submit",
            body=json.dumps({"line": "ui", "clientRequestId": "r2"}).encode(),
            via="studio",
        )
        assert host.started[1].via == "studio"

    asyncio.run(scenario())


def _sse_payload(chunk: bytes) -> dict:
    """从 SSE 分块里取出 data 帧。"""
    for line in chunk.splitlines():
        if line.startswith(b"data: "):
            return json.loads(line[len(b"data: ") :])
    raise AssertionError(f"no data line in {chunk!r}")


def test_events_keep_frames_published_before_first_read(tmp_path: Path) -> None:
    """订阅必须在取重放快照之前：handler 返回后、首次读取前发的帧不能丢。"""

    async def scenario() -> None:
        transport, host = _transport(tmp_path)
        response = await transport.request("GET", "/rt/r1/events", last_event_id="0")
        assert response.stream is not None
        await host.broadcaster.publish({"kind": "text", "text": "a"})
        await host.broadcaster.publish({"kind": "text", "text": "b"})
        first = await asyncio.wait_for(response.stream.__anext__(), timeout=1.0)
        second = await asyncio.wait_for(response.stream.__anext__(), timeout=1.0)
        assert _sse_payload(first)["text"] == "a"
        assert _sse_payload(second)["text"] == "b"

    asyncio.run(scenario())


def test_events_dedupe_live_frames_already_replayed(tmp_path: Path) -> None:
    """先订阅再重放会产生重复：seq ≤ 重放高位必须跳过。"""

    async def scenario() -> None:
        transport, host = _transport(tmp_path)
        for index in range(3):
            await host.broadcaster.publish({"kind": "text", "text": str(index)})
        response = await transport.request("GET", "/rt/r1/events", last_event_id="0")
        assert response.stream is not None
        await host.broadcaster.publish({"kind": "text", "text": "3"})
        texts = []
        for _ in range(4):
            chunk = await asyncio.wait_for(response.stream.__anext__(), timeout=1.0)
            texts.append(_sse_payload(chunk)["text"])
        assert texts == ["0", "1", "2", "3"]

    asyncio.run(scenario())


def test_history_unknown_block_degrades_to_text(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """未知内容块不得把 /history 打成 500：降级为文本占位。"""
    from questorharness.bootstrap.hosts.serve import routes

    monkeypatch.setattr(
        routes,
        "load_session_snapshot",
        lambda cwd: {
            "session_id": "sid",
            "messages": [{"role": "assistant", "content": [{"type": "thinking"}]}],
        },
    )

    async def scenario() -> None:
        transport, _ = _transport(tmp_path)
        response = await transport.request("GET", "/rt/r1/history")
        assert response.status == 200
        block = _json(response)["messages"][0]["blocks"][0]
        assert block["type"] == "text"
        assert "unsupported block" in block["text"]

    asyncio.run(scenario())


def test_unknown_route_is_404(tmp_path: Path) -> None:
    """未注册端点 404（停工症状 §6-5 的触发点）。"""

    async def scenario() -> None:
        transport, _ = _transport(tmp_path)
        response = await transport.request("GET", "/rt/r1/nope")
        assert response.status == 404

    asyncio.run(scenario())
