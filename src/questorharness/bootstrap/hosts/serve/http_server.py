"""aiohttp 适配：只做 request/response 转换与鉴权，路由仍归 routes.py。

回环主机、随机端口、五件套校验都在这里落地；handler 对传输无感。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Final

from aiohttp import web

from questorharness.bootstrap.hosts.serve import auth, refusals
from questorharness.bootstrap.hosts.serve.transport import Handler, Request, Response

_BIND_HOST: Final[str] = "127.0.0.1"


class HttpServer:
    """回环 HTTP 宿主：同一组 handler，加一层凭据与字节传输。"""

    def __init__(
        self,
        handler: Handler,
        credential: auth.LaunchCredential,
        *,
        allow_no_auth: bool = False,
    ) -> None:
        if not credential.token or len(credential.token) < auth.TOKEN_MIN_BYTES:
            raise ValueError("launch credential is too short")
        self._handler = handler
        self._credential = credential
        self._allow_no_auth = allow_no_auth
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self.port: int = 0

    def app(self) -> web.Application:
        """构造只有一个 catch-all 路由的应用。"""
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", self._handle)
        return app

    async def start(self) -> int:
        """绑定 127.0.0.1 的随机端口并返回实际端口。"""
        self._runner = web.AppRunner(self.app())
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, _BIND_HOST, 0)
        await self._site.start()
        server = self._site._server
        sockets = getattr(server, "sockets", None) or []
        if not sockets:
            raise RuntimeError("loopback listener did not bind a socket")
        self.port = int(sockets[0].getsockname()[1])
        return self.port

    async def close(self) -> None:
        """关闭监听与连接。"""
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
            self._site = None

    async def _handle(self, request: web.Request) -> web.StreamResponse:
        """鉴权 → 转换 → 交给 handler → 写回（含 SSE 流）。"""
        try:
            self._authorize(request)
            converted = await self._convert(request)
            response = await self._handler(converted)
        except refusals.Refusal as exc:
            return web.json_response({"code": exc.code, "message": exc.message}, status=exc.status)
        headers = dict(response.headers)
        headers.setdefault("X-Questor-Client", str(converted.client_id))
        if response.stream is None:
            return web.Response(status=response.status, body=response.body, headers=headers)
        return await self._stream(request, response, headers)

    def _authorize(self, request: web.Request) -> None:
        """五件套里的 ②③④：token cookie、Host、Origin。"""
        if self._allow_no_auth:
            return
        auth.validate_host(request.host)
        auth.validate_origin(request.headers.get("Origin"))
        auth.validate_cookie(request.cookies, self._credential)

    async def _convert(self, request: web.Request) -> Request:
        """把 aiohttp 请求转成传输无关 Request。"""
        client_id = request.headers.get(auth.CLIENT_HEADER) or uuid.uuid4().hex
        body = await request.read() if request.method in {"POST", "PUT", "PATCH"} else b""
        return Request(
            method=request.method,
            path=request.path,
            client_id=client_id,
            query=dict(request.query),
            body=body,
            last_event_id=request.headers.get("Last-Event-ID"),
        )

    async def _stream(
        self, request: web.Request, response: Response, headers: dict[str, str]
    ) -> web.StreamResponse:
        """把 AsyncIterator[bytes] 写成 chunked 响应。"""
        assert response.stream is not None
        stream: AsyncIterator[bytes] = response.stream
        prepared = web.StreamResponse(status=response.status, headers=headers)
        await prepared.prepare(request)
        async for chunk in stream:
            await prepared.write(chunk)
        await prepared.write_eof()
        return prepared
