"""P7 T8/T4：sidecar 一并伺服前端静态产物（webview 指本服务根路径，ADR-0007）。

create_app(server, static_dir) 给定存在的目录时把其挂到 `/`；API 路由（/health、/run、/events…）
精确匹配优先，其余（含 `/`）走静态。这里用 starlette TestClient 验"根路径返回首页 HTML + API 仍在"，
属装配接线验证（真 webview 像素渲染仍 UNVERIFIED）。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from questor.providers.fake import EchoProvider
from questor.providers.store_sqlite import SQLiteStore
from questor.surfaces.cli import CliSurface
from questor.surfaces.http_sse import EventServer, create_app


async def test_sidecar_serves_static_shell(tmp_path: Path) -> None:
    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text("<html><body>Questor Static Shell</body></html>", encoding="utf-8")

    store = await SQLiteStore(str(tmp_path / "static.db")).connect()
    try:
        server = EventServer(CliSurface(workspace_root=tmp_path, store=store, provider=EchoProvider()), store)
        app = create_app(server, static_dir=static)
        with TestClient(app) as client:
            root = client.get("/")
            assert root.status_code == 200
            assert "Questor Static Shell" in root.text
            # API 未被静态挂载吞掉。
            assert client.get("/health").json() == {"status": "ok"}
    finally:
        await store.close()


async def test_no_static_dir_keeps_api_only(tmp_path: Path) -> None:
    # 未给 static_dir（或目录不存在）→ 不挂静态：根路径 404，但 API 仍工作（REPL/无 UI 的 headless serve）。
    store = await SQLiteStore(str(tmp_path / "api.db")).connect()
    try:
        server = EventServer(CliSurface(workspace_root=tmp_path, store=store, provider=EchoProvider()), store)
        with TestClient(create_app(server)) as client:
            assert client.get("/health").status_code == 200
            assert client.get("/").status_code == 404
    finally:
        await store.close()
