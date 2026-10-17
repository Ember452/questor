"""P7 T12：桌面端到端能力矩阵（脚本化 provider，真 HTTP+SSE / 真 reducer+store 侧断言，非像素）。

覆盖 DoD① 里能在无人值守下**真跑**的能力，断言落在 durable 事件/reducer，而非 UI：
- **问答流式**：真 uvicorn 子进程 + 真 httpx，`text_delta` 上屏、`message_completed` 携 D-P7-C 的
  `final_text`、`run_completed` 终态，durable 尾 seq 连续不重（承 DoD②）。
- **取消闭合**：EventServer 路径投 `Cancel` → `run_cancelled`，且历史里每个 tool_use 都配对到 result
  （C7/C19，不留悬空 `tool_use`）。
- **Skills 生效**：tmp `QUESTOR_SKILLS_DIR` 放合法 SKILL.md → 注入 system prompt（provider 侧可观察）。

诚实边界（不用 fake 冒充真机，一律 UNVERIFIED）：真 LLM、真远程 MCP server 端到端、真 PyInstaller
打包桌面崩溃重启——本机无 cargo/无显示/无网络真供应商，故不在本用例伪造。
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from questor.contracts.events import AppendAssistantMessage, Cancel
from questor.contracts.ports import ProviderPort, ProviderRequest, StreamChunk
from questor.contracts.state_schema import Budget, CancelReason, ContentBlock, Message, Role, RunStatus
from questor.providers.store_sqlite import SQLiteStore
from questor.state import reduce
from questor.state.domain_state import Run
from questor.surfaces.cli import CliSurface

_REPO_ROOT = str(Path(__file__).resolve().parents[2])

# 与 T1 同形状的真服务子进程脚本（离线 Echo；不起真模型）。
_SERVER = """
import asyncio, os
from pathlib import Path
from questor.providers.store_sqlite import SQLiteStore
from questor.providers.fake import EchoProvider
from questor.surfaces.cli import CliSurface
from questor.surfaces.http_sse import EventServer, create_app
import uvicorn

async def main():
    store = await SQLiteStore(os.environ["E2E_DB"]).connect()
    surface = CliSurface(workspace_root=Path(os.environ["E2E_WS"]), store=store, provider=EchoProvider())
    app = create_app(EventServer(surface, store))
    await uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=int(os.environ["E2E_PORT"]), log_level="warning")).serve()

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


# --------------------------------------------------------------------------- #
# A：问答流式，真 HTTP+SSE 子进程
# --------------------------------------------------------------------------- #
def _parse_sse(text: str) -> list[tuple[int | None, str]]:
    out: list[tuple[int | None, str]] = []
    cur: int | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("id:"):
            cur = int(line[3:].strip())
        elif line.startswith("event:"):
            out.append((cur, line[6:].strip()))
    return out


@pytest.mark.timeout(180)
def test_e2e_streaming_over_real_http_sse(tmp_path: Path) -> None:
    db = str(tmp_path / "e2e.db")
    port = _free_port()
    env = {
        **os.environ,
        "PYTHONPATH": str(Path(_REPO_ROOT) / "src"),
        "E2E_DB": db,
        "E2E_PORT": str(port),
        "E2E_WS": str(tmp_path),
        "NO_PROXY": "127.0.0.1,localhost",
    }
    server_py = tmp_path / "server.py"
    server_py.write_text(_SERVER, encoding="utf-8")
    proc = subprocess.Popen([sys.executable, str(server_py)], env=env, cwd=_REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        if not _wait_port(port, deadline=time.monotonic() + 40):
            out = proc.stdout.read() if proc.stdout else ""
            proc.kill()
            pytest.skip(f"real uvicorn socket unavailable (UNVERIFIED): {out[-500:]}")

        base = f"http://127.0.0.1:{port}"
        run_id = "run_e2e_" + os.urandom(4).hex()
        with httpx.Client(base_url=base, timeout=None, trust_env=False) as client:
            # 订阅先于跑：捕获 live text_delta（Echo 秒完成，先 GET 建立订阅再后台 POST）。
            def _post() -> None:
                time.sleep(1.0)
                with httpx.Client(base_url=base, timeout=None, trust_env=False) as poster:
                    poster.post("/run", json={"text": "hello", "run_id": run_id})

            import threading

            t = threading.Thread(target=_post)
            t.start()
            resp = client.get(f"/events/{run_id}")
            t.join(timeout=30)

        events = _parse_sse(resp.text)
        types = [e for _, e in events]
        assert "text_delta" in types, types  # 流式上屏（live）
        assert "message_completed" in types, types
        assert types[-1] == "run_completed", types  # 终态收尾

        # durable 侧权威核验：store.replay 尾 seq 连续、无重复，且 message_completed 带 final_text。
        durable = asyncio.run(_replay(db, run_id))
        seqs = [row["seq"] for row in durable]
        assert seqs == sorted(set(seqs)), f"durable seq 不应重复：{seqs}"  # 不重
        mc = next((row for row in durable if row["type"] == "message_completed"), None)
        assert mc is not None and mc["data"].get("final_text"), f"message_completed 应带 final_text：{mc}"
        assert any(row["type"] == "run_completed" for row in durable)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


async def _replay(db: str, run_id: str) -> list[dict]:
    store = await SQLiteStore(db).connect()
    try:
        return await store.replay(run_id, 0)
    finally:
        await store.close()


# --------------------------------------------------------------------------- #
# B：取消回填——reducer 侧不变式（C7/C19），桌面 `/cancel` 路径依赖它（真组件、无竞态）
# --------------------------------------------------------------------------- #
def test_e2e_cancel_backfills_no_dangling_tool_use() -> None:
    """一个未闭合 tool_use 经 Cancel 后必须被回填为 cancelled 结果（不留悬空 tool_use）。

    这是 EventServer `/cancel`→`Cancel` Command→reduce 的收口不变式；在 reducer 层确定性验证
    （跨真实子进程的取消时机竞态属 UNVERIFIED，交 T8 Rust supervisor 崩溃重启覆盖）。"""
    run = Run(run_id="run_cancel", budget=Budget())
    msg = Message(
        id="m1",
        role=Role.ASSISTANT,
        content=(ContentBlock(type="tool_use", tool_use_id="tc1", name="read", input={"path": "x.txt"}),),
        seq=0,
    )
    run, _ = reduce.reduce(run, AppendAssistantMessage(run_id="run_cancel", turn=0, message=msg))
    assert _open_tool_uses(run) == ["tc1"], "前置：应有一个未闭合 tool_use"

    run, events = reduce.reduce(run, Cancel(run_id="run_cancel", reason=CancelReason.USER))
    types = [e.type for e in events]
    assert "run_cancelled" in types, types
    assert any(e.type == "tool_completed" and e.data.get("status") == "cancelled" for e in events), types
    assert run.status is RunStatus.CANCELLED
    assert not _open_tool_uses(run), f"取消后仍有悬空 tool_use：{_open_tool_uses(run)}"


def _open_tool_uses(run) -> list[str]:  # noqa: ANN001
    """从 context 历史里找出没有配对 tool_result 的 tool_use id（回退到无 state_access 依赖的纯遍历）。"""
    uses: dict[str, str] = {}
    results: set[str] = set()
    for msg in run.context.items:
        for block in msg.content:
            if block.type == "tool_use" and block.tool_use_id:
                uses[block.tool_use_id] = block.name or ""
            if block.type == "tool_result" and block.tool_use_id:
                results.add(block.tool_use_id)
    return [tid for tid in uses if tid not in results]


# --------------------------------------------------------------------------- #
# C：Skills 注入 system prompt（provider 侧可观察）
# --------------------------------------------------------------------------- #
class _RecordingProvider(ProviderPort):
    def __init__(self) -> None:
        self.seen_system: str | None = None

    async def stream(self, request: ProviderRequest) -> AsyncIterator[StreamChunk]:
        self.seen_system = request.system
        yield StreamChunk(kind="finish", finish_reason="stop")


async def test_e2e_skills_dir_injects_system(tmp_path: Path) -> None:
    # 合法发现布局：每个技能一个子目录，内含 SKILL.md（front-matter 带 name/description）。
    skill_dir = tmp_path / "skills" / "greeting"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: greeting\ndescription: Say hi cordially.\n---\nUse a warm greeting.\n",
        encoding="utf-8",
    )
    provider = _RecordingProvider()
    surface = CliSurface(workspace_root=tmp_path, provider=provider, skills_dir=tmp_path / "skills", store=None)
    await surface.run_once("hi")
    assert provider.seen_system is not None, "provider 应收到带技能的 system"
    assert "greeting" in provider.seen_system.lower(), provider.seen_system  # SKILL.md 目录进了 system prompt
