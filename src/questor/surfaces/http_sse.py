"""L6 HTTP + SSE 事件服务（ADR-0007/0013；design/02 §4）。P1 T10 + P2 T13。

零业务逻辑（STRUCTURE S6）：端点只把 Command（提交/审批/改权限/取消）*投进*该 run 的
Command Inbox，再把事件流*投影*成 SSE。绝不直接 reduce。
续传是一等能力：``GET /events/{run_id}`` 遵从 ``Last-Event-ID``/``after_seq``，先经 store
重放 durable 尾、再跟实时，每帧带 ``id: <seq>``。

SSE 帧/头风格改形自 CowAgent ``openai_compat.py``；``id:<seq>`` + after_seq 重放接线为本仓
自写（两个参考都未暴露它——R10 §⑤）。"""

from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from questor.contracts.common import new_id, thaw
from questor.contracts.events import Cancel, Envelope, EventType, ResolveApproval, SetPermissionMode, SubmitMessage
from questor.contracts.inbox import InboxStatus
from questor.contracts.state_schema import Budget, CancelReason, ContentBlock, Message, Role
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.run_control import RunController
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import Run
from questor.surfaces.cli import CliSurface
from questor.surfaces.run_registry import RunRegistry

# 终态事件集：流式跟到这些即停。
TERMINAL = {EventType.RUN_COMPLETED, EventType.RUN_CANCELLED, EventType.RUN_FAILED}


def envelope_to_json(env: Envelope) -> str:
    """把一个事件信封序列化为 wire JSON（data 经 thaw 还原为普通 dict）。"""
    return json.dumps(
        {"v": env.v, "seq": env.seq, "run_id": env.run_id, "turn": env.turn, "ts": env.ts.isoformat(), "type": env.type, "data": thaw(env.data)},
        ensure_ascii=False,
        default=str,
    )


def envelope_to_frame(env: Envelope) -> dict:
    """SSE 帧：行首 ``id: <seq>`` 作续传游标 + 完整信封作 data。"""
    return {"id": str(env.seq), "event": env.type, "data": envelope_to_json(env)}


class EventServer:
    """持有端点共享的 store + bus + active run 的 Command Inbox 注册表。"""

    def __init__(self, surface: CliSurface, store: SQLiteStore) -> None:
        self.surface = surface
        self.store = store
        self.bus = InProcessEventBus(store)
        self.registry = RunRegistry()

    def _loop(self, cancel: asyncio.Event) -> DefaultTurnLoop:
        """复用 surface 的装配，但挂到本服务共享的 bus 上。"""
        return self.surface._loop(self.bus, cancel)

    async def start_run(self, text: str, run_id: str | None = None) -> str:
        """后台启动一次 run（用户文本经 SubmitMessage Command 进入 inbox）。"""
        run_id = run_id or new_id("run")
        run = Run(run_id=run_id, budget=Budget())
        controller = RunController(run)
        self.registry.register(controller)
        msg = Message(id=new_id("msg"), role=Role.USER, content=(ContentBlock(type="text", text=text),), seq=0)
        await self.registry.submit(run_id, SubmitMessage(run_id=run_id, content=msg), source="http", idempotency_key=f"submit:{run_id}")
        task = asyncio.create_task(self._loop(asyncio.Event()).drive_controller(controller))
        self.registry.set_task(run_id, task)
        return run_id

    async def resolve_approval(self, run_id: str, request_id: str, decision: str) -> str:
        """把审批决策投进该 run 的 inbox；返回 receipt status。"""
        if decision not in {"allow", "deny"}:
            raise HTTPException(status_code=400, detail="decision must be allow or deny")
        receipt = await self.registry.submit(
            run_id,
            ResolveApproval(run_id=run_id, request_id=request_id, decision=decision, decided_by="http_client"),
            source="http",
            idempotency_key=request_id,
        )
        if not receipt.accepted and receipt.status is InboxStatus.UNKNOWN_RUN:
            raise HTTPException(status_code=404, detail=receipt.reason)
        return receipt.status.value

    async def set_permission_mode(self, run_id: str, mode: str, changed_by: str = "http_client") -> str:
        """改未来调用的权限模式；同样只经 inbox。"""
        if mode not in {"default", "plan", "full_auto"}:
            raise HTTPException(status_code=400, detail="invalid permission mode")
        receipt = await self.registry.submit(
            run_id,
            SetPermissionMode(run_id=run_id, mode=mode, changed_by=changed_by),
            source="http",
            idempotency_key=f"mode:{run_id}:{mode}",
        )
        if not receipt.accepted and receipt.status is InboxStatus.UNKNOWN_RUN:
            raise HTTPException(status_code=404, detail=receipt.reason)
        return receipt.status.value

    async def cancel(self, run_id: str) -> str:
        """请求取消某 run（Cancel Command 经 inbox 在安全点收尾）。"""
        receipt = await self.registry.submit(
            run_id,
            Cancel(run_id=run_id, reason=CancelReason.USER),
            source="http",
            idempotency_key=f"cancel:{run_id}",
        )
        if not receipt.accepted and receipt.status is InboxStatus.UNKNOWN_RUN:
            raise HTTPException(status_code=404, detail=receipt.reason)
        return receipt.status.value

    async def stream(self, run_id: str, after_seq: int = 0):
        """产出 SSE 帧：先重放 after_seq 之后、再跟实时，至终态停并清理 active run。"""
        async for env in self.bus.subscribe(run_id, after_seq):
            yield envelope_to_frame(env)
            if env.type in TERMINAL:
                self.registry.unregister(run_id)
                return


def create_app(server: EventServer) -> FastAPI:
    """构建 FastAPI 应用：run/cancel/approve/permissions/events 全部只投 Command 或投事件。"""
    app = FastAPI(title="questor", version="0.1.0")

    @app.post("/run")
    async def run(payload: dict) -> dict:
        run_id = await server.start_run(payload.get("text", ""), payload.get("run_id"))
        return {"run_id": run_id}

    @app.post("/runs/{run_id}/cancel")
    async def cancel_run(run_id: str) -> dict:
        return {"status": await server.cancel(run_id)}

    # 兼容 P1 端点。
    @app.post("/cancel/{run_id}")
    async def cancel_legacy(run_id: str) -> dict:
        return {"status": await server.cancel(run_id)}

    @app.post("/runs/{run_id}/approvals/{request_id}/resolve")
    async def resolve(run_id: str, request_id: str, payload: dict) -> dict:
        return {"status": await server.resolve_approval(run_id, request_id, payload.get("decision", ""))}

    @app.post("/runs/{run_id}/permissions")
    async def permissions(run_id: str, payload: dict) -> dict:
        return {"status": await server.set_permission_mode(run_id, payload.get("mode", ""))}

    @app.get("/events/{run_id}")
    async def events(request: Request, run_id: str, after_seq: int = 0) -> EventSourceResponse:
        """SSE 事件流；优先用 ``Last-Event-ID`` 头作续传游标。"""
        header = request.headers.get("last-event-id")
        if header and header.isdigit():
            after_seq = int(header)
        return EventSourceResponse(server.stream(run_id, after_seq))

    return app
