"""P3 T14：真 socket SSE after_seq 重连不丢不重（ROADMAP P3 判据②）。

起一个**真 uvicorn 服务**（子进程）+ **真 httpx 客户端**打真 TCP loopback，闭合 P2 审计 §7 的
"跨真实 socket 的 SSE 重连 UNVERIFIED（uvicorn 未装）"：run 到终态后，断开→带 ``Last-Event-ID`` 重连
→ 断言只拿到 ``seq > mid`` 的 durable 尾、无缺口、无重复、终态恰一条。durable 集以**同一文件 store**
的 ``replay`` 为权威基准比对。delta 属 live-only、不入库故不在重放里（不占 durable seq）。
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from questor.providers.store_sqlite import SQLiteStore

_REPO_ROOT = str(Path(__file__).resolve().parents[2])

_SERVER = """
import asyncio, os
from pathlib import Path
from questor.providers.store_sqlite import SQLiteStore
from questor.providers.fake import EchoProvider
from questor.surfaces.cli import CliSurface
from questor.surfaces.http_sse import EventServer, create_app
import uvicorn

async def main():
    db = os.environ["SSE_DB"]
    port = int(os.environ["SSE_PORT"])
    ws = os.environ["SSE_WS"]
    store = await SQLiteStore(db).connect()
    surface = CliSurface(workspace_root=Path(ws), store=store, provider=EchoProvider())
    server = EventServer(surface, store)
    app = create_app(server)
    await uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")).serve()

asyncio.run(main())
"""


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_port(port: int, deadline: float) -> bool:
    while time.monotonic() < deadline:
        with socket.socket() as s:
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.15)
    return False


def _parse_sse(text: str) -> list[tuple[int | None, str]]:
    pairs: list[tuple[int | None, str]] = []
    cur_id: int | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("id:"):
            cur_id = int(line[3:].strip())
        elif line.startswith("event:"):
            pairs.append((cur_id, line[6:].strip()))
    return pairs


async def _durable_tail(db: str, run_id: str, after: int) -> list[int]:
    store = await SQLiteStore(db).connect()
    try:
        return [row["seq"] for row in await store.replay(run_id, after)]
    finally:
        await store.close()


async def _wait_terminal(db: str, run_id: str, deadline: float) -> list[str]:
    """轮询同一文件 store，直到该 run 落任一终态事件；返回其 durable 事件序列。"""
    terminal = {"run_completed", "run_cancelled", "run_failed"}
    while time.monotonic() < deadline:
        store = await SQLiteStore(db).connect()
        try:
            rows = await store.replay(run_id, 0)
        finally:
            await store.close()
        types = [r["type"] for r in rows]
        if any(t in terminal for t in types):
            return [r["seq"] for r in rows]
        await asyncio.sleep(0.1)
    raise AssertionError("run never reached a terminal event within deadline")


@pytest.mark.timeout(180)
def test_sse_real_socket_reconnect_no_loss_no_dup(tmp_path: Path) -> None:
    db = str(tmp_path / "sse.db")
    port = _free_port()
    env = {
        **os.environ,
        "PYTHONPATH": str(Path(_REPO_ROOT) / "src"),
        "SSE_DB": db,
        "SSE_PORT": str(port),
        "SSE_WS": str(tmp_path),
        # hermetic：不让系统代理干扰 loopback（服务端与客户端都不走代理）。
        "NO_PROXY": "127.0.0.1,localhost",
    }
    server_py = tmp_path / "server.py"
    server_py.write_text(_SERVER, encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, str(server_py)],
        env=env,
        cwd=_REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        if not _wait_port(port, deadline=time.monotonic() + 40):
            out = proc.stdout.read() if proc.stdout else ""
            proc.kill()
            pytest.skip(f"real uvicorn socket unavailable in this environment (UNVERIFIED): {out[-500:]}")

        base = f"http://127.0.0.1:{port}"
        # trust_env=False → 忽略环境里的 HTTP_PROXY/HTTPS_PROXY，避免代理把 loopback 请求劫成 502（审计 B1）。
        with httpx.Client(base_url=base, timeout=None, trust_env=False) as client:
            run_id = client.post("/run", json={"text": "hello"}).json()["run_id"]
            seqs = asyncio.run(_wait_terminal(db, run_id, deadline=time.monotonic() + 20))
            assert len(seqs) >= 2, seqs  # 至少 run_started + 终态

            mid = seqs[0]
            expected_tail = seqs[1:]

            # 断开后重连：带 Last-Event-ID=mid → 只应拿到 durable 尾（不丢不重）。
            resp = client.get(f"/events/{run_id}", headers={"Last-Event-ID": str(mid)})
            pairs = _parse_sse(resp.text)
            got_seqs = [p[0] for p in pairs if p[0] is not None]

            assert got_seqs == expected_tail  # 无缺口、无重复
            assert pairs[-1][1] in {"run_completed", "run_cancelled", "run_failed"}  # 终态恰一条、在最后
            # 交叉校验：重连结果与 store 权威尾一致
            assert asyncio.run(_durable_tail(db, run_id, mid)) == got_seqs
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
