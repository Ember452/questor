"""端到端：真实 MCP 工具经 Harness 执行并**先入 event_log 再投影**（T7 / DoD②④；C13/C19/C17）。

真子进程 demo server + 真 SQLiteStore + 真 turn 循环 + 脚本化 provider 调用 `mcp_demo_echo`。
两条判据：
① 有网络围栏（`fences_network`）时工具真执行、结果入 ledger、`tool_started/tool_completed` 落 event_log；
② 无围栏（默认 none sandbox）时 C17 capability floor 把 NETWORK 工具 **fail-closed deny**（mode 不能放宽），
   但**配对仍闭合**（deny 也写 tool_result），run 不崩——证明"远程能力不因 MCP 被静默放宽"。
store/连接在 finally 关闭（aiosqlite 不关漏非守护线程 → 被本仓 conftest 线程守卫抓红）。"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from mcp import StdioServerParameters

from questor.capabilities.mcp.connection import McpConnection
from questor.capabilities.mcp.remote_tool import McpRemoteTool
from questor.contracts.common import new_id
from questor.contracts.events import SetPermissionMode
from questor.contracts.ports import ProviderPort, ProviderRequest, StreamChunk
from questor.contracts.sandbox import Confinement, SandboxBackend, SandboxDescriptor
from questor.contracts.state_schema import Budget, ToolCallStatus
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.policy.react_policy import ReActPolicy
from questor.providers.store_sqlite import SQLiteStore
from questor.state.checkpoint import open_tool_use_ids
from questor.state.domain_state import Run
from questor.state.reduce import reduce

SERVER = Path(__file__).resolve().parents[1] / "support" / "mcp_demo_server.py"


class _ScriptProvider(ProviderPort):
    def __init__(self) -> None:
        self._i = 0

    async def stream(self, request: ProviderRequest) -> AsyncIterator[StreamChunk]:
        if self._i == 0:
            self._i += 1
            yield StreamChunk(kind="tool_call", tool_call={"index": 0, "id": "tc_1", "name": "mcp_demo_echo", "args_delta": '{"text": "hi"}'})
            yield StreamChunk(kind="finish", finish_reason="tool_calls")
        else:
            yield StreamChunk(kind="text", text="done")
            yield StreamChunk(kind="finish", finish_reason="stop")


class _NetSandbox:
    """声明"有网络围栏"的 sandbox（describe-only，够 loop 权限求值用）。"""

    def describe(self) -> SandboxDescriptor:
        return SandboxDescriptor(
            backend=SandboxBackend.BWRAP,
            confinement=Confinement.FULL,
            fences_writes=True,
            fences_network=True,
            isolates_process_tree=True,
            limitation="test network-fenced sandbox",
        )


def _make_loop(provider, store, tools, tmp_path, sandbox):
    by_name = {t.spec.name: t for t in tools}
    bus = InProcessEventBus(store)
    loop = DefaultTurnLoop(
        provider=provider,
        policy=ReActPolicy(),
        permission=DefaultPermissionEngine(),
        bus=bus,
        tool_for=by_name.get,
        tools=tuple(tools),
        store=store,
        workspace_root=tmp_path,
        model="test",
        sandbox=sandbox,
    )
    return loop, bus


async def _tools_from(conn) -> list[McpRemoteTool]:
    raw = await conn.list_tools()
    return [
        McpRemoteTool(connection=conn, server_name="demo", raw_name=t.name, description=str(t.description or ""), input_schema=t.inputSchema)
        for t in raw
    ]


@pytest.mark.asyncio
async def test_network_fenced_mcp_tool_executes_into_event_log(tmp_path: Path) -> None:
    store = await SQLiteStore(tmp_path / "state.db").connect()
    conn = McpConnection(StdioServerParameters(command=sys.executable, args=[str(SERVER)]), errlog=sys.stderr)
    await conn.start()
    try:
        tools = await _tools_from(conn)
        loop, _bus = _make_loop(_ScriptProvider(), store, tools, tmp_path, _NetSandbox())
        run = Run(run_id=new_id("run"), budget=Budget(max_turns=4))
        run, _ = reduce(run, SetPermissionMode(run_id=run.run_id, mode="full_auto", changed_by="test"))
        final = await loop.drive(run, "call echo please")

        assert final.status.value == "completed", final.status
        call = next(c for c in final.tool_ledger.calls if c.tool_call_id == "tc_1")
        assert call.status is ToolCallStatus.SUCCESS, (call.status, call.permission_reason)
        assert "hi" in str(call.result)
        assert open_tool_use_ids(final.context.items) == ()
        types = [r["type"] for r in await store.replay(final.run_id, 0)]
        assert "tool_started" in types and "tool_completed" in types  # 结果先进 event_log
    finally:
        await conn.aclose()
        await store.close()


@pytest.mark.asyncio
async def test_no_network_fence_denies_mcp_tool_but_closes_pairing(tmp_path: Path) -> None:
    """C17：无网络围栏时 NETWORK 工具被 floor fail-closed deny；配对仍闭合、run 不崩。"""
    store = await SQLiteStore(tmp_path / "state.db").connect()
    conn = McpConnection(StdioServerParameters(command=sys.executable, args=[str(SERVER)]), errlog=sys.stderr)
    await conn.start()
    try:
        tools = await _tools_from(conn)
        loop, _bus = _make_loop(_ScriptProvider(), store, tools, tmp_path, sandbox=None)  # → none descriptor
        run = Run(run_id=new_id("run"), budget=Budget(max_turns=4))
        run, _ = reduce(run, SetPermissionMode(run_id=run.run_id, mode="full_auto", changed_by="test"))
        final = await loop.drive(run, "call echo please")

        call = next(c for c in final.tool_ledger.calls if c.tool_call_id == "tc_1")
        # 合法 args 的 NETWORK 工具在 none sandbox 下被拒 == capability floor（mode=full_auto 无法放宽，C17）。
        assert call.status is ToolCallStatus.DENIED, call.status
        assert not call.result or "success" not in str(call.result).lower()
        assert open_tool_use_ids(final.context.items) == (), "deny 也必须回 tool_result 闭合配对"
        assert final.status.value == "completed", "被拒不等于崩溃；run 正常收尾"
    finally:
        await conn.aclose()
        await store.close()
