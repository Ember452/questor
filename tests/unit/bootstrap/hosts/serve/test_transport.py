"""transport 模块镜像测试：内存传输的请求/响应与流。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from questorharness.bootstrap.hosts.serve.transport import (
    MemoryTransport,
    Request,
    Response,
)


def test_memory_transport_passes_request_through() -> None:
    """memory transport 只转发，不改写。"""
    seen: list[Request] = []

    async def handler(request: Request) -> Response:
        seen.append(request)
        return Response(status=201, body=b"ok")

    async def scenario() -> None:
        transport = MemoryTransport(handler)
        response = await transport.request("POST", "/x", body=b"{}", client_id="c1")
        assert response.status == 201
        assert seen[0].client_id == "c1"
        assert seen[0].body == b"{}"

    asyncio.run(scenario())


def test_drain_collects_stream_chunks() -> None:
    """流式响应必须能被完整消费（REPL 与测试共用）。"""

    async def stream() -> AsyncIterator[bytes]:
        yield b"a"
        yield b"b"

    async def scenario() -> None:
        transport = MemoryTransport(lambda request: _never(request))
        payload = await transport.drain(Response(status=200, stream=stream()))
        assert payload == b"ab"

    async def _never(request: Request) -> Response:  # pragma: no cover - 占位
        raise AssertionError("handler must not be called")

    asyncio.run(scenario())
