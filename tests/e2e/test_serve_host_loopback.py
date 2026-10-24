"""回环宿主 e2e：五件套判红与多客户端归属。

引擎回合循环用注入替身（保持 turn 运行以测归属），其余全是真的：
HttpServer、鉴权、router、authority、broadcaster。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from questorharness.bootstrap.hosts.serve import ServeHost, auth
from questorharness.bootstrap.hosts.serve.authority import Authority
from questorharness.bootstrap.hosts.serve.http_server import HttpServer
from questorharness.contracts.domain.events import StatusEvent

PROFILE_YAML = "name: coding\ndescription: loopback\nui:\n  capabilities:\n    chat: ready\n"


def _host(tmp_path: Path) -> ServeHost:
    """构造一个只依赖 stub runtime 的宿主。"""
    (tmp_path / "coding.yaml").write_text(PROFILE_YAML, encoding="utf-8")
    runtime = SimpleNamespace(cwd=str(tmp_path), session_id="sid")
    return ServeHost(runtime, authority=Authority(), profile_root=tmp_path)  # type: ignore[arg-type]


def test_loopback_auth_matrix_and_client_ownership(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """无 cookie/错 token/错 Origin/错 Host 均拒；持有者才能取消。"""

    async def hanging(bundle, line, *, print_system, render_event, clear_output, user_message=None):  # type: ignore[no-untyped-def]
        await asyncio.sleep(30)
        return True

    from questorharness.bootstrap import runtime as runtime_module

    monkeypatch.setattr(runtime_module, "handle_line", hanging, raising=True)

    async def scenario() -> None:
        host = _host(tmp_path)
        credential = auth.LaunchCredential.issue()
        server = HttpServer(host.router, credential)
        port = await server.start()
        base = f"http://127.0.0.1:{port}"
        origin = {"Origin": base}
        cookie = {auth.COOKIE_NAME: credential.token}
        try:
            async with httpx.AsyncClient() as client:
                assert (
                    await client.get(f"{base}/rt/r1/profile", headers=origin)
                ).status_code == 401
                bad_token = await client.get(
                    f"{base}/rt/r1/profile",
                    headers=origin,
                    cookies={auth.COOKIE_NAME: "wrong"},
                )
                assert bad_token.status_code == 401
                bad_origin = await client.post(
                    f"{base}/rt/r1/submit",
                    headers={"Origin": "https://evil.example.com"},
                    json={"line": "hi", "clientRequestId": "bad-origin"},
                    cookies=cookie,
                )
                assert bad_origin.status_code == 403
                assert bad_origin.json()["code"] == "auth.origin"
                # 浏览器同源 GET 不带 Origin：GET 不得因缺头被 403。
                browser_get = await client.get(f"{base}/rt/r1/profile", cookies=cookie)
                assert browser_get.status_code == 200
                bad_host = await client.get(
                    f"{base}/rt/r1/profile",
                    headers={"Host": "evil.example.com", "Origin": base},
                    cookies=cookie,
                )
                assert bad_host.status_code == 403
                assert bad_host.json()["code"] == "auth.host"

                ok = await client.get(f"{base}/rt/r1/profile", headers=origin, cookies=cookie)
                assert ok.status_code == 200
                assert ok.json()["ui"]["capabilities"]["chat"] == "ready"

                submit = await client.post(
                    f"{base}/rt/r1/submit",
                    headers={**origin, auth.CLIENT_HEADER: "owner"},
                    cookies=cookie,
                    json={"line": "work", "clientRequestId": "r1"},
                )
                assert submit.status_code == 202
                await asyncio.sleep(0.05)

                intruder = await client.post(
                    f"{base}/rt/r1/cancel",
                    headers={**origin, auth.CLIENT_HEADER: "intruder"},
                    cookies=cookie,
                )
                assert intruder.status_code == 409
                assert intruder.json()["code"] == "turn.not_owner"

                owner = await client.post(
                    f"{base}/rt/r1/cancel",
                    headers={**origin, auth.CLIENT_HEADER: "owner"},
                    cookies=cookie,
                )
                assert owner.status_code == 200
                await asyncio.gather(*host._tasks.values(), return_exceptions=True)
        finally:
            await server.close()

    asyncio.run(scenario())


def test_settled_prompt_is_rejected_twice(tmp_path: Path) -> None:
    """未知/已结算 id 走 approval.already_settled（同一码，客户端可分支）。"""

    async def scenario() -> None:
        host = _host(tmp_path)
        credential = auth.LaunchCredential.issue()
        server = HttpServer(host.router, credential)
        port = await server.start()
        base = f"http://127.0.0.1:{port}"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{base}/rt/r1/approve",
                    headers={"Origin": base},
                    cookies={auth.COOKIE_NAME: credential.token},
                    json={"id": "nope", "decision": "approve"},
                )
                assert response.status_code == 409
                assert response.json()["code"] == "approval.already_settled"
        finally:
            await server.close()

    asyncio.run(scenario())


def test_two_clients_race_the_same_approval(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """同一个审批 id：再答一次 → already_settled；非持有者 → not_owner。"""

    holder: dict[str, Any] = {}

    async def prompt_turn(
        bundle, line, *, print_system, render_event, clear_output, user_message=None
    ):  # type: ignore[no-untyped-def]
        host = holder["host"]
        allowed = await host.authority.permission_prompt("bash", "danger")
        await render_event(StatusEvent(message=f"allowed={allowed}"))
        return True

    from questorharness.bootstrap import runtime as runtime_module

    monkeypatch.setattr(runtime_module, "handle_line", prompt_turn, raising=True)

    async def wait_for_prompt(host: ServeHost) -> str:
        for _ in range(200):
            for _, frame in host.broadcaster.replay(0).frames:
                if frame["kind"] == "approval_request":
                    return str(frame["id"])
            await asyncio.sleep(0.01)
        raise AssertionError("approval_request never arrived")

    async def scenario() -> None:
        host = _host(tmp_path)
        holder["host"] = host
        credential = auth.LaunchCredential.issue()
        server = HttpServer(host.router, credential)
        port = await server.start()
        base = f"http://127.0.0.1:{port}"
        origin = {"Origin": base}
        cookie = {auth.COOKIE_NAME: credential.token}
        try:
            async with httpx.AsyncClient() as client:
                submit = await client.post(
                    f"{base}/rt/r1/submit",
                    headers={**origin, auth.CLIENT_HEADER: "owner"},
                    cookies=cookie,
                    json={"line": "needs approval", "clientRequestId": "appr-1"},
                )
                assert submit.status_code == 202
                prompt_id = await wait_for_prompt(host)

                intruder = await client.post(
                    f"{base}/rt/r1/approve",
                    headers={**origin, auth.CLIENT_HEADER: "intruder"},
                    cookies=cookie,
                    json={"id": prompt_id, "decision": "approve"},
                )
                assert intruder.status_code == 409
                assert intruder.json()["code"] == "approval.not_owner"

                first = await client.post(
                    f"{base}/rt/r1/approve",
                    headers={**origin, auth.CLIENT_HEADER: "owner"},
                    cookies=cookie,
                    json={"id": prompt_id, "decision": "approve"},
                )
                assert first.status_code == 200

                second = await client.post(
                    f"{base}/rt/r1/approve",
                    headers={**origin, auth.CLIENT_HEADER: "owner"},
                    cookies=cookie,
                    json={"id": prompt_id, "decision": "deny"},
                )
                assert second.status_code == 409
                assert second.json()["code"] == "approval.already_settled"
                await asyncio.wait_for(asyncio.gather(*host._tasks.values()), timeout=30)
        finally:
            await server.close()

    asyncio.run(scenario())


def test_handshake_and_short_token_guard(tmp_path: Path) -> None:
    """握手单行 JSON；短 token 直接拒绝构造。"""

    async def scenario() -> None:
        host = _host(tmp_path)
        credential = auth.LaunchCredential.issue()
        payload = json.loads(auth.handshake_payload(1234, credential))
        assert payload["token"] == credential.token
        assert len(payload["token"]) >= auth.TOKEN_MIN_BYTES
        with pytest.raises(ValueError):
            HttpServer(host.router, auth.LaunchCredential(token="tiny"))

    asyncio.run(scenario())
