"""回环 HTTP 适配单测：鉴权矩阵与响应头。"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from questorharness.bootstrap.hosts.serve import auth
from questorharness.bootstrap.hosts.serve.http_server import HttpServer
from questorharness.bootstrap.hosts.serve.transport import Request, Response


def _server(*, allow_no_auth: bool = False) -> tuple[HttpServer, auth.LaunchCredential]:
    """构造一个回显 handler 的服务器。"""

    async def handler(request: Request) -> Response:
        return Response(
            status=200,
            body=b'{"path":"' + request.path.encode() + b'"}',
            headers={"content-type": "application/json"},
        )

    credential = auth.LaunchCredential.issue()
    return HttpServer(handler, credential, allow_no_auth=allow_no_auth), credential


def test_unauthenticated_request_is_rejected() -> None:
    """无 cookie → 401 auth.required。"""

    async def scenario() -> None:
        server, _ = _server()
        port = await server.start()
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"http://127.0.0.1:{port}/rt/r1/profile",
                    headers={"Origin": f"http://127.0.0.1:{port}"},
                )
            assert response.status_code == 401
            assert response.json()["code"] == "auth.required"
        finally:
            await server.close()

    asyncio.run(scenario())


def test_wrong_host_origin_and_token_are_rejected() -> None:
    """Host / Origin / token 各自有独立拒绝码。"""

    async def scenario() -> None:
        server, credential = _server()
        port = await server.start()
        cookie = {auth.COOKIE_NAME: credential.token}
        try:
            async with httpx.AsyncClient() as client:
                bad_host = await client.get(
                    f"http://127.0.0.1:{port}/x",
                    headers={"Host": "evil.example.com", "Origin": f"http://127.0.0.1:{port}"},
                    cookies=cookie,
                )
                assert bad_host.status_code == 403
                assert bad_host.json()["code"] == "auth.host"
                bad_origin = await client.get(
                    f"http://127.0.0.1:{port}/x",
                    headers={"Origin": "https://evil.example.com"},
                    cookies=cookie,
                )
                assert bad_origin.status_code == 403
                assert bad_origin.json()["code"] == "auth.origin"
                bad_token = await client.get(
                    f"http://127.0.0.1:{port}/x",
                    headers={"Origin": f"http://127.0.0.1:{port}"},
                    cookies={auth.COOKIE_NAME: "nope"},
                )
                assert bad_token.status_code == 401
        finally:
            await server.close()

    asyncio.run(scenario())


def test_authorized_request_echoes_client_id() -> None:
    """通过鉴权后回显 X-Questor-Client，便于多客户端归属。"""

    async def scenario() -> None:
        server, credential = _server()
        port = await server.start()
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"http://127.0.0.1:{port}/rt/r1/profile",
                    headers={
                        "Origin": f"http://127.0.0.1:{port}",
                        auth.CLIENT_HEADER: "client-a",
                    },
                    cookies={auth.COOKIE_NAME: credential.token},
                )
            assert response.status_code == 200
            assert response.headers[auth.CLIENT_HEADER] == "client-a"
        finally:
            await server.close()

    asyncio.run(scenario())


def test_allow_no_auth_is_dev_only_and_explicit() -> None:
    """显式开启 dev 模式才跳过五件套（默认路径必须鉴权）。"""

    async def scenario() -> None:
        server, _ = _server(allow_no_auth=True)
        port = await server.start()
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"http://127.0.0.1:{port}/x")
            assert response.status_code == 200
        finally:
            await server.close()

    asyncio.run(scenario())


def test_short_token_is_rejected_at_construction() -> None:
    """短 token 不允许构造，防误配。"""
    with pytest.raises(ValueError):
        HttpServer(lambda request: None, auth.LaunchCredential(token="short"))  # type: ignore[arg-type]
