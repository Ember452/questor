"""T13 surfaces：CLI/HTTP 审批都必须只经 RunRegistry 提交 Command（ADR-0013/C16）。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from questor.contracts.common import new_id
from questor.contracts.events import Envelope, EventType, ResolveApproval
from questor.contracts.inbox import InboxStatus
from questor.contracts.state_schema import Budget
from questor.kernel.events import InProcessEventBus
from questor.kernel.run_control import RunController
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import Run
from questor.surfaces.cli import CliSurface
from questor.surfaces.http_sse import EventServer, create_app
from questor.surfaces.run_registry import RunRegistry


async def test_registry_rejects_unknown_run() -> None:
    registry = RunRegistry()
    receipt = await registry.submit(
        "missing",
        ResolveApproval(run_id="missing", request_id="apr", decision="allow", decided_by="test"),
        source="http",
        idempotency_key="apr",
    )
    assert receipt.status is InboxStatus.UNKNOWN_RUN


async def _wait_commands(controller: RunController, timeout: float = 1.0) -> tuple:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        commands = await controller.next_batch()
        if commands:
            return commands
        await asyncio.sleep(0.01)
    return ()


async def _cancel_quietly(task: asyncio.Task) -> None:
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def test_cli_approve_submits_deny_command_without_reducing(tmp_path: Path) -> None:
    """非交互 CLI 看到 approval_request 只能提交 ResolveApproval(deny) 进 inbox，绝不直接改状态。"""
    run_id = new_id("run")
    controller = RunController(Run(run_id=run_id, budget=Budget()))
    registry = RunRegistry()
    registry.register(controller)
    bus = InProcessEventBus(None)
    surface = CliSurface(workspace_root=tmp_path)

    # 先同步挂上订阅队列，再启动监听（store=None 时只有 live 事件），然后 emit approval_request。
    queue = bus.add_subscriber(run_id)
    listener = asyncio.create_task(surface._approve(queue, registry, run_id))
    await asyncio.sleep(0)
    await bus.emit(
        Envelope(
            v=1,
            seq=1,
            run_id=run_id,
            type=EventType.APPROVAL_REQUEST,
            data={"request_id": "apr-1", "tool_call_id": "tc", "name": "write", "args_summary": "x", "risk": "medium", "reason": "no fence", "expires_at": ""},
        )
    )
    commands = await _wait_commands(controller)
    await _cancel_quietly(listener)
    resolve = next(c for c in commands if isinstance(c, ResolveApproval))
    assert resolve.decision == "deny"
    assert resolve.decided_by == "cli"


def test_http_resolve_validation_and_routes() -> None:
    async def _run() -> None:
        store = await SQLiteStore(":memory:").connect()
        try:
            server = EventServer(CliSurface(), store)
            with pytest.raises(HTTPException) as bad:
                await server.resolve_approval("missing", "apr", "maybe")
            assert bad.value.status_code == 400
            with pytest.raises(HTTPException) as missing:
                await server.resolve_approval("missing", "apr", "allow")
            assert missing.value.status_code == 404
        finally:
            await store.close()

    asyncio.run(_run())


async def test_app_exposes_approval_and_permission_routes() -> None:
    store = await SQLiteStore(":memory:").connect()
    try:
        app = create_app(EventServer(CliSurface(), store))
        paths = {route.path for route in app.routes}
        assert "/runs/{run_id}/approvals/{request_id}/resolve" in paths
        assert "/runs/{run_id}/permissions" in paths
        assert "/runs/{run_id}/cancel" in paths
    finally:
        await store.close()
