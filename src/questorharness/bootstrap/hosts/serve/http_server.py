"""aiohttp 适配：只做 request/response 转换与鉴权，路由仍归 routes.py。

回环主机、随机端口、五件套校验都在这里落地；handler 对传输无感。
"""

from __future__ import annotations

import mimetypes
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Final

from aiohttp import web

from questorharness.bootstrap.hosts.serve import auth, refusals
from questorharness.bootstrap.hosts.serve.transport import Handler, Request, Response

_BIND_HOST: Final[str] = "127.0.0.1"
_STATEFUL_METHODS: Final[frozenset[str]] = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class HttpServer:
    """回环 HTTP 宿主：同一组 handler，加一层凭据与字节传输。"""

    def __init__(
        self,
        handler: Handler,
        credential: auth.LaunchCredential,
        *,
        allow_no_auth: bool = False,
        static_root: Path | None = None,
    ) -> None:
        if not credential.token or len(credential.token) < auth.TOKEN_MIN_BYTES:
            raise ValueError("launch credential is too short")
        self._handler = handler
        self._credential = credential
        self._allow_no_auth = allow_no_auth
        self._static_root = static_root.resolve() if static_root is not None else None
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
        # 静态资源（仅回环、仅 GET）不进鉴权：Electron 需要在种 cookie 前先加载 index。
        if self._static_root is not None and request.method == "GET":
            if not request.path.startswith("/rt/"):
                static = self._serve_static(request.path)
                if static is not None:
                    return static
                # 静态根存在但文件缺失：直接 404，不要回落到鉴权层（会误报 401）。
                return web.json_response(
                    {"code": refusals.NOT_FOUND, "message": f"no static file for GET {request.path}"},
                    status=404,
                )
        try:
            self._authorize(request)
            client_id, minted = self._client_identity(request)
            converted = await self._convert(request, client_id)
            response = await self._handler(converted)
        except refusals.Refusal as exc:
            return web.json_response({"code": exc.code, "message": exc.message}, status=exc.status)
        headers = dict(response.headers)
        headers.setdefault("X-Questor-Client", str(converted.client_id))
        if minted:
            # 浏览器无 header 可用：首次请求种植身份 cookie，后续审批/提交才是同一人。
            headers["Set-Cookie"] = auth.client_cookie(converted.client_id)
        if response.stream is None:
            return web.Response(status=response.status, body=response.body, headers=headers)
        return await self._stream(request, response, headers)

    def _serve_static(self, path: str) -> web.Response | None:
        """从 `apps/web/dist` 回放 SPA：`/` → index.html；未知路径 → None（交给路由）。"""
        assert self._static_root is not None
        relative = "index.html" if path in {"/", ""} else path.lstrip("/")
        candidate = (self._static_root / relative).resolve()
        if self._static_root not in candidate.parents and candidate != self._static_root:
            return None
        if not candidate.is_file():
            return None
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        return web.Response(
            status=200,
            body=candidate.read_bytes(),
            headers={"content-type": content_type, "cache-control": "no-cache"},
        )

    def _authorize(self, request: web.Request) -> None:
        """五件套里的 ②③④：Host、Origin（仅改状态方法）、token cookie。

        Origin 只对 POST/PUT/PATCH/DELETE 强制：浏览器同源 GET（fetch/EventSource）
        往往不发 Origin，对所有方法统一强校验会把 /events、/history 全拦成 403。
        GET 的回环防护由 Host + SameSite=Strict cookie 承担。
        """
        if self._allow_no_auth:
            return
        auth.validate_host(request.host)
        if request.method in _STATEFUL_METHODS:
            auth.validate_origin(request.headers.get("Origin"))
        auth.validate_cookie(request.cookies, self._credential)

    def _client_identity(self, request: web.Request) -> tuple[str, bool]:
        """header → 身份 cookie → 现铸；返回 (client_id, 是否新铸需要种 cookie)。"""
        header = request.headers.get(auth.CLIENT_HEADER)
        if header:
            return header, False
        cookie = request.cookies.get(auth.CLIENT_COOKIE)
        if cookie:
            return cookie, False
        return uuid.uuid4().hex, True

    async def _convert(self, request: web.Request, client_id: str) -> Request:
        """把 aiohttp 请求转成传输无关 Request；经 TCP 提交的 via 是 studio。"""
        body = await request.read() if request.method in {"POST", "PUT", "PATCH"} else b""
        return Request(
            method=request.method,
            path=request.path,
            client_id=client_id,
            query=dict(request.query),
            body=body,
            last_event_id=request.headers.get("Last-Event-ID"),
            via="studio",
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
