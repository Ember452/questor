"""回环宿主 e2e：五件套判红与多客户端归属。

引擎回合循环用注入替身（保持 turn 运行以测归属），其余全是真的：
HttpServer、鉴权、router、authority、broadcaster。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from questorharness.bootstrap.hosts.serve import ServeHost, auth
from questorharness.bootstrap.hosts.serve.authority import Authority
from questorharness.bootstrap.hosts.serve.http_server import HttpServer

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
                bad_origin = await client.get(
                    f"{base}/rt/r1/profile",
                    headers={"Origin": "https://evil.example.com"},
                    cookies=cookie,
                )
                assert bad_origin.status_code == 403
                assert bad_origin.json()["code"] == "auth.origin"
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
                await asyncio.gather(*host._tasks.values(), return_exceptions=True)  # noqa: SLF001
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
