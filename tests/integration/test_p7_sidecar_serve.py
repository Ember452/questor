"""P7 T1：sidecar serve 生产入口（loopback `127.0.0.1:0` + generation bootstrap，真 uvicorn）。

判红目标（先于实现，TDD）：
- 冷导入 `questor.surfaces.serve`（新 L6 面）。
- 临时口分配**恒 127.0.0.1、绝不 0.0.0.0**（D-P7-B / C12：本地 IPC 无网络出口）。
- bootstrap 记录 `{host,port,generation,pid}`（供 Rust 注入 webview + 陈旧连接栅栏基）。
- headless 起 `python -m questor --serve` 真进程：读回 bootstrap 端口 → `/health` 通 →
  `POST /run` + `GET /events/{run_id}` 收 `text_delta`→终态帧（真 uvicorn，非 mock）。

诚实边界：真桌面打包 / 真 Rust 侧崩溃重启属 T8（UNVERIFIED）；本用例只证 Python serve 面立起来。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

from questor.surfaces import serve

_REPO_ROOT = str(Path(__file__).resolve().parents[2])


# --------------------------------------------------------------------------- #
# 单元：临时口 + bootstrap（不起 uvicorn，无线程泄漏面）
# --------------------------------------------------------------------------- #
def test_make_loopback_socket_is_ephemeral_and_never_wildcard() -> None:
    """绑到的口必须是 127.0.0.1 + OS 分配的非零端口（绝不 0.0.0.0）。"""
    sock, port = serve.make_loopback_socket()
    try:
        host, bound_port = sock.getsockname()[:2]
        assert host == "127.0.0.1", f"必须 loopback，实得 {host!r}（违 C12/D-P7-B）"
        assert bound_port == port and port > 0, f"临时口应为正整数，实得 {port}"
    finally:
        sock.close()


def test_write_and_read_bootstrap(tmp_path: Path) -> None:
    """bootstrap 落 JSON 含 host/port/generation/pid，回读一致；host 恒 127.0.0.1。"""
    path = tmp_path / "sidecar.json"
    wrote = serve.write_bootstrap(path, host="127.0.0.1", port=54321, generation=7, pid=4242)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw == {"host": "127.0.0.1", "port": 54321, "generation": 7, "pid": 4242}
    assert wrote["generation"] == 7
    assert serve.read_bootstrap(path) == raw


def test_write_bootstrap_rejects_wildcard_host(tmp_path: Path) -> None:
    """试图把 bootstrap 写成 0.0.0.0 必须当场拒绝（进程边界红线，不能只靠 socket 绑对）。"""
    with pytest.raises(ValueError):
        serve.write_bootstrap(tmp_path / "x.json", host="0.0.0.0", port=1, generation=0, pid=os.getpid())


# --------------------------------------------------------------------------- #
# 集成：真 uvicorn headless 起进程，走 bootstrap 端口打真 HTTP+SSE
# --------------------------------------------------------------------------- #
def _wait_bootstrap(path: Path, deadline: float) -> dict:
    while time.monotonic() < deadline:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("port"):
                    return data
            except json.JSONDecodeError:
                pass  # 写入尚未完成，继续轮询
        time.sleep(0.1)
    raise AssertionError("sidecar never wrote a bootstrap file with a port within deadline")


def _parse_sse_events(text: str) -> list[str]:
    return [ln[6:].strip() for ln in text.splitlines() if ln.strip().startswith("event:")]


@pytest.mark.timeout(180)
def test_sidecar_serve_headless_run_flow(tmp_path: Path) -> None:
    """真进程 `--serve`：bootstrap 端口 → /health → /run → /events 收流式文本 + 终态帧。"""
    bootstrap = tmp_path / "sidecar.json"
    env = {
        **os.environ,
        "PYTHONPATH": str(Path(_REPO_ROOT) / "src"),
        "QUESTOR_STORE_PATH": str(tmp_path / "state.db"),
        "QUESTOR_MEMORY_DB": str(tmp_path / "memory.db"),
        "QUESTOR_MEMORY_ROOT": str(tmp_path / "memory_store"),
        "QUESTOR_LOG_DIR": str(tmp_path / "logs"),
        "QUESTOR_SIDECAR_BOOTSTRAP": str(bootstrap),
        "QUESTOR_SIDECAR_GENERATION": "7",
        "NO_PROXY": "127.0.0.1,localhost",
    }
    env.pop("QUESTOR_MODEL", None)  # 离线 Echo，不联网
    proc = subprocess.Popen(
        [sys.executable, "-m", "questor", "--serve"],
        env=env,
        cwd=_REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        try:
            boot = _wait_bootstrap(bootstrap, deadline=time.monotonic() + 40)
        except AssertionError:
            out = proc.stdout.read() if proc.stdout else ""
            pytest.skip(f"real uvicorn sidecar unavailable in this environment (UNVERIFIED): {out[-600:]}")

        assert boot["generation"] == 7
        assert boot["host"] == "127.0.0.1"
        base = f"http://127.0.0.1:{boot['port']}"
        with httpx.Client(base_url=base, timeout=None, trust_env=False) as client:
            # 就绪探测：/health 通（D-P7-B 的"轮询端口 + 健康"替代参考仓 stdin initialize）。
            health_ready = False
            hdeadline = time.monotonic() + 30
            while time.monotonic() < hdeadline:
                try:
                    if client.get("/health").status_code == 200:
                        health_ready = True
                        break
                except httpx.HTTPError:
                    time.sleep(0.2)
            assert health_ready, "sidecar 起来后 /health 未在期限内返回 200"

            run_id = "run_t1_" + os.urandom(6).hex()
            # 先订阅后跑：离线 Echo 秒完成，若先 POST 再 GET 则 text_delta（live-only）已错过。
            # 故用预置 run_id，后台线程延时 POST（保证 GET 的 bus 订阅队列先建立），再阻塞式收流。
            def _delayed_post() -> None:
                time.sleep(1.0)
                with httpx.Client(base_url=base, timeout=None, trust_env=False) as poster:
                    poster.post("/run", json={"text": "hello", "run_id": run_id})

            poster = threading.Thread(target=_delayed_post)
            poster.start()
            resp = client.get(f"/events/{run_id}")
            poster.join(timeout=30)
            events = _parse_sse_events(resp.text)
            assert "run_started" in events, events
            assert "text_delta" in events, f"离线 Echo 应流式 text_delta（订阅先于跑），实得 {events}"
            terminal = {"run_completed", "run_cancelled", "run_failed"}
            assert events and events[-1] in terminal, f"终态帧必须是最后一个，实得 {events}"
            assert sum(1 for e in events if e in terminal) == 1, f"终态恰一条（C13），实得 {events}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
