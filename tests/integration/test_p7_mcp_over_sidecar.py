"""P7 §6-7 收口：MCP 远程工具经 **sidecar/桌面路径**（EventServer.start_run）被发现并进入工具面。

审计 §5-4/§6-7 指出：`EventServer.start_run/resume` 曾用 `registry.freeze_for_run` 绕过 `_discover_mcp`
→ 桌面/GUI 路径**永不出现远程 MCP 工具**（只有 CLI run_once 有）。本用例真起 stdio demo server，
经 EventServer 跑一轮 provider 调 `mcp_demo_echo`，断言：

- 该 tool_call **被识别为远程工具**：默认 none sandbox 下 NETWORK 工具被 C17 capability floor **fail-closed deny**
  → `tool_completed{status:"denied"}`；若未接线则会是 `status:"error"`（"unknown tool"）。二者区分 = 接线证据。
- run 正常收尾（被拒不崩），per-run MCP teardown 随 `_drive_and_teardown` 回收连接/子进程（finally 里 store/无泄漏）。

真远程（非本地 stdio）MCP server 端到端仍属 UNVERIFIED（网络受限）。"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path

from questor.contracts.ports import ProviderPort, ProviderRequest, StreamChunk
from questor.providers.store_sqlite import SQLiteStore
from questor.surfaces.cli import CliSurface
from questor.surfaces.http_sse import EventServer

SERVER = Path(__file__).resolve().parents[1] / "support" / "mcp_demo_server.py"


class _McpCallProvider(ProviderPort):
    """turn1 请求调用远程工具 mcp_demo_echo；turn2 收尾。"""

    def __init__(self) -> None:
        self._i = 0

    async def stream(self, request: ProviderRequest) -> AsyncIterator[StreamChunk]:
        self._i += 1
        if self._i == 1:
            yield StreamChunk(kind="tool_call", tool_call={"index": 0, "id": "tc_mcp", "name": "mcp_demo_echo", "args_delta": '{"text":"hi"}'})
            yield StreamChunk(kind="finish", finish_reason="tool_calls")
        else:
            yield StreamChunk(kind="text", text="done")
            yield StreamChunk(kind="finish", finish_reason="stop")


async def test_mcp_reachable_over_sidecar_path(tmp_path: Path) -> None:
    mcp_json = tmp_path / "mcp.json"
    mcp_json.write_text(json.dumps({"mcpServers": {"demo": {"command": sys.executable, "args": [str(SERVER)]}}}), encoding="utf-8")

    store = await SQLiteStore(str(tmp_path / "mcp.db")).connect()
    try:
        surface = CliSurface(workspace_root=tmp_path, store=store, provider=_McpCallProvider(), mcp_json_path=mcp_json)
        server = EventServer(surface, store)
        run_id = await server.start_run("call echo", run_id="run_mcp_desktop")

        # 轮询 durable 直到终态（真 stdio server 启动需时间）。
        terminal = {"run_completed", "run_cancelled", "run_failed"}
        durable: list[dict] = []
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            durable = await store.replay(run_id, 0)
            if any(r["type"] in terminal for r in durable):
                break
            await _sleep(0.1)
        by_seq = {r["seq"]: r for r in durable}
        completed = [r for r in durable if r["type"] == "tool_completed"]
        assert completed, f"未见 tool_completed：{[r['type'] for r in durable]}"
        # 接线证据：远程工具被识别 → none sandbox 下 C17 floor fail-closed deny（status=denied），
        # 而非"unknown tool"（未接线会 status=error）。
        statuses = [r["data"].get("status") for r in completed]
        assert "denied" in statuses, f"远程工具应被识别并在无网络围栏下 deny（证明已接进桌面路径），实得 {statuses}"
        assert "error" not in statuses, f"不应是 'unknown tool' 错误（=未接线），实得 {statuses}"
        assert any(r["type"] == "run_completed" for r in durable), by_seq  # 被拒不崩，run 正常收尾
        # 配对闭合：tool_completed 存在即 tool_use 已回填（无悬空），终态恰一。
        assert sum(1 for r in durable if r["type"] in terminal) == 1
    finally:
        await store.close()


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)
