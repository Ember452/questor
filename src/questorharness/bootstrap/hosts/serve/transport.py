"""传输抽象：进程内 memory transport 与后续的回环 TCP 共用同一组路由。

Request/Response 是纯数据；``Response.stream`` 承载 SSE 字节流，谁生成它
由路由决定，因此两条传输的语义完全一致。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Request:
    """一次请求的纯数据形态。"""

    method: str
    path: str
    client_id: str = "local"
    query: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""
    last_event_id: str | None = None
    via: str = "studio"


@dataclass
class Response:
    """一次响应；``stream`` 非空时 ``body`` 应为空。"""

    status: int
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)
    stream: AsyncIterator[bytes] | None = None


class Handler(Protocol):
    """路由入口：transport 只负责调用它。"""

    async def __call__(self, request: Request) -> Response: ...


class Transport(Protocol):
    """传输契约。"""

    async def handle(self, request: Request) -> Response: ...


class MemoryTransport:
    """进程内传输：不开端口、无凭据、主机名从不解析。"""

    def __init__(self, handler: Handler) -> None:
        self._handler = handler

    async def handle(self, request: Request) -> Response:
        """满足 Transport 契约。"""
        return await self._handler(request)

    async def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        client_id: str = "local",
        query: Mapping[str, str] | None = None,
        last_event_id: str | None = None,
        via: str = "cli",
    ) -> Response:
        """客户端便捷入口（REPL 与测试共用）；进程内提交的 via 是 cli。"""
        return await self.handle(
            Request(
                method=method,
                path=path,
                client_id=client_id,
                query=query or {},
                body=body or b"",
                last_event_id=last_event_id,
                via=via,
            )
        )

    async def drain(self, response: Response) -> bytes:
        """把流式响应读完（测试与 REPL 的同步消费点）。"""
        if response.stream is None:
            return response.body
        chunks: list[bytes] = []
        async for chunk in response.stream:
            chunks.append(chunk)
        return b"".join(chunks)
