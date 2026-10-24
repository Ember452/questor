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


def test_unknown_route_is_404(tmp_path: Path) -> None:
    """未注册端点 404（停工症状 §6-5 的触发点）。"""

    async def scenario() -> None:
        transport, _ = _transport(tmp_path)
        response = await transport.request("GET", "/rt/r1/nope")
        assert response.status == 404

    asyncio.run(scenario())
