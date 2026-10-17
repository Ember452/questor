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
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from questor.contracts.common import new_id, thaw
from questor.contracts.events import Cancel, Envelope, EventType, ResolveApproval, SetPermissionMode, SubmitMessage
from questor.contracts.inbox import InboxReceipt
from questor.contracts.ports import StorePort
from questor.contracts.state_schema import Budget, CancelReason, ContentBlock, Message, Role
from questor.contracts.tool import RunToolSurface
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.recovery import rebuild_run
from questor.kernel.run_control import RunController
from questor.observability.projection import log_envelope
from questor.state.domain_state import Run
from questor.surfaces.approval import http_status_for_receipt
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


def _receipt_response(receipt: InboxReceipt) -> JSONResponse:
    """把 receipt 变成带映射状态码的 JSON 响应（<400 才会到这里，>=400 已在 _checked 抛）。"""
    return JSONResponse(status_code=http_status_for_receipt(receipt), content={"status": receipt.status.value, "reason": receipt.reason})


class EventServer:
    """持有端点共享的 store + bus + active run 的 Command Inbox 注册表。"""

    def __init__(self, surface: CliSurface, store: StorePort) -> None:
        self.surface = surface
        self.store = store
        # 让 EventServer 构造的 turn loop 也持久化 checkpoint（P3 resume 前置）；surface 仍只持 StorePort 抽象。
        if surface.store is None:
            surface.store = store
        self.bus = InProcessEventBus(store)
        # bus 级唯一只读投影订阅（ADR-0033 / D-P7-A）：sidecar 路径的事件带外行也落主干日志
        # （收口 plan/05 §0.4 缺口：`stream()` 曾完全不投）。挂在此处一次，与 SSE 订阅者数量无关。
        self.bus.add_observer(log_envelope)
        self.registry = RunRegistry()
        # 优雅关闭信号：`/shutdown` 置位，serve 面的看门狗据此让 uvicorn 应声停机（不等 grace 超时硬杀）。
        self.shutdown_event = asyncio.Event()

    def request_shutdown(self) -> None:
        """请求优雅关闭（仅置信号，不硬杀）；serve 看门狗会拾起并让 uvicorn 退出。"""
        self.shutdown_event.set()

    def _loop(self, cancel: asyncio.Event, surface: RunToolSurface) -> DefaultTurnLoop:
        """复用 surface 的装配，但挂到本服务共享的 bus 上（工具面来自冻结 surface）。"""
        return self.surface._loop(self.bus, cancel, surface)

    async def _run_with_mcp(self, controller: RunController, run_id: str) -> None:
        """发现 MCP → 冻结工具面 → 驱动到终态 → per-run teardown。四步**必须同任务**。

        MCP stdio 会话的 anyio cancel scope 在哪个 task 进入就必须在那个 task 退出；若把 discover 放在
        start_run（调用方 task）而 teardown 放在驱动 task，会“exit cancel scope in a different task”崩。
        故发现/驱动/回收集中在此一个 task 内；无 mcp.json 时 discover 返回 ([], noop)，不改变既有行为。
        """
        mcp_tools, mcp_teardown = await self.surface._discover_mcp(run_id)
        tool_surface = self.surface._freeze_surface(run_id, mcp_tools)
        try:
            await self._loop(asyncio.Event(), tool_surface).drive_controller(controller)
        finally:
            await mcp_teardown()  # 关连接+回收子进程树+stderr 句柄，防泄漏

    async def start_run(self, text: str, run_id: str | None = None) -> str:
        """后台启动一次 run（用户文本经 SubmitMessage Command 进入 inbox）。

        MCP per-run 发现接进桌面路径（审计 §6-7），且与驱动/teardown 同任务（anyio 会话作组作用域）。
        """
        run_id = run_id or new_id("run")
        run = Run(run_id=run_id, budget=Budget())
        controller = RunController(run)
        self.registry.register(controller)
        msg = Message(id=new_id("msg"), role=Role.USER, content=(ContentBlock(type="text", text=text),), seq=0)
        await self.registry.submit(run_id, SubmitMessage(run_id=run_id, content=msg), source="http", idempotency_key=f"submit:{run_id}")
        task = asyncio.create_task(self._run_with_mcp(controller, run_id))
        self.registry.set_task(run_id, task)
        return run_id

    async def resolve_approval(self, run_id: str, request_id: str, decision: str) -> InboxReceipt:
        """把审批决策投进该 run 的 inbox；返回 receipt（>=400 的映射码直接抛 HTTPException）。"""
        if decision not in {"allow", "deny"}:
            raise HTTPException(status_code=400, detail="decision must be allow or deny")
        return self._checked(
            await self.registry.submit(
                run_id,
                ResolveApproval(run_id=run_id, request_id=request_id, decision=decision, decided_by="http_client"),
                source="http",
                idempotency_key=request_id,
            )
        )

    async def set_permission_mode(self, run_id: str, mode: str, changed_by: str = "http_client") -> InboxReceipt:
        """改未来调用的权限模式；同样只经 inbox。"""
        if mode not in {"default", "plan", "full_auto"}:
            raise HTTPException(status_code=400, detail="invalid permission mode")
        return self._checked(
            await self.registry.submit(
                run_id,
                SetPermissionMode(run_id=run_id, mode=mode, changed_by=changed_by),
                source="http",
                idempotency_key=f"mode:{run_id}:{mode}",
            )
        )

    async def cancel(self, run_id: str) -> InboxReceipt:
        """请求取消某 run（Cancel Command 经 inbox 在安全点收尾）。"""
        return self._checked(
            await self.registry.submit(
                run_id,
                Cancel(run_id=run_id, reason=CancelReason.USER),
                source="http",
                idempotency_key=f"cancel:{run_id}",
            )
        )

    async def resume(self, run_id: str) -> str:
        """从持久态续跑一个被 kill/重启的 run（P3，ADR-0021）。

        surfaces 零业务：rebuild 不直 reduce（交给 kernel）；重建的 run 经 RunController 注册回
        Command Inbox，使后续 HTTP 审批/取消能路由到续跑中的 run。无快照 → 404。
        """
        run = await rebuild_run(self.store, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"no checkpoint for run {run_id}")
        controller = RunController(run)
        self.registry.register(controller)
        task = asyncio.create_task(self._run_with_mcp(controller, run_id))  # 续跑面同样接 MCP（同任务 discover+drive+teardown）
        self.registry.set_task(run_id, task)
        return run_id

    @staticmethod
    def _checked(receipt: InboxReceipt) -> InboxReceipt:
        """receipt 映射的 HTTP 码 >=400 时抛 HTTPException（surface 不碰 reduce，只据 receipt 说话）。"""
        code = http_status_for_receipt(receipt)
        if code >= 400:
            raise HTTPException(status_code=code, detail=receipt.reason)
        return receipt

    async def stream(self, run_id: str, after_seq: int = 0, *, expected_version: int | None = None):
        """产出 SSE 帧：先（版本闸门后）重放 after_seq 之后、再跟实时，至终态停并清理 active run。

        ``expected_version``（客户端契约版本）不匹配时，总线只发一条 ``resync_required`` 然后停，
        绝不跨版本解码（C6；design/02 §10 版本闸门接消费者）。
        """
        async for env in self.bus.subscribe(run_id, after_seq, expected_version=expected_version):
            yield envelope_to_frame(env)
            if env.type in TERMINAL:
                self.registry.unregister(run_id)
                return


def create_app(server: EventServer, static_dir: Path | None = None, token: str | None = None) -> FastAPI:
    """构建 FastAPI 应用：run/cancel/approve/permissions/events 全部只投 Command 或投事件。

    ``static_dir``（存在时）挂载到 ``/``：桌面壳把 webview 指向本服务（ADR-0007），前端静态产物
    由 sidecar 一并伺服（前端只同源调本 API，不新增跨源面）。属控制平面装配，不触事件协议/契约。

    ``token``（给定则启用）为**会话 token**：除 `/health` 就绪探针外，所有命令/事件端点都要校验
    请求头 `x-questor-token` 或查询参数 `token`，缺失/不符→401。堵住"本机任意进程驱动 agent 跑 run、
    伪造审批"的裸 loopback 暴露面（HITL 是安全边界，不能被本地旁路）。None=不强制（REPL/测试/headless）。
    """
    app = FastAPI(title="questor", version="0.1.0")

    def require_token(request: Request) -> None:
        """会话 token 门：token=None 放行；否则头或查询参数须匹配，否则 401（fail-closed）。"""
        if token is None:
            return
        provided = request.headers.get("x-questor-token") or request.query_params.get("token")
        if provided != token:
            raise HTTPException(status_code=401, detail="missing or invalid sidecar token")

    @app.get("/health")
    async def health() -> dict:
        """就绪探针（D-P7-B）：Rust 侧轮询本端口替代参考仓的 stdin `initialize`——只证 serve 面起来，不触碰任何状态。"""
        return {"status": "ok"}

    @app.post("/shutdown", dependencies=[Depends(require_token)])
    async def shutdown() -> dict:
        """优雅关闭 RPC（§6-6）：壳关窗时 POST 此端点，serve 看门狗让 uvicorn 在 grace 内自退（Exited 非恒 ForceKilled）。"""
        server.request_shutdown()
        return {"status": "shutting_down"}

    @app.post("/run", dependencies=[Depends(require_token)])
    async def run(payload: dict) -> dict:
        run_id = await server.start_run(payload.get("text", ""), payload.get("run_id"))
        return {"run_id": run_id}

    @app.post("/runs/{run_id}/cancel", dependencies=[Depends(require_token)])
    async def cancel_run(run_id: str) -> JSONResponse:
        return _receipt_response(await server.cancel(run_id))

    # 兼容 P1 端点。
    @app.post("/cancel/{run_id}", dependencies=[Depends(require_token)])
    async def cancel_legacy(run_id: str) -> JSONResponse:
        return _receipt_response(await server.cancel(run_id))

    @app.post("/runs/{run_id}/approvals/{request_id}/resolve", dependencies=[Depends(require_token)])
    async def resolve(run_id: str, request_id: str, payload: dict) -> JSONResponse:
        return _receipt_response(await server.resolve_approval(run_id, request_id, payload.get("decision", "")))

    @app.post("/runs/{run_id}/permissions", dependencies=[Depends(require_token)])
    async def permissions(run_id: str, payload: dict) -> JSONResponse:
        return _receipt_response(await server.set_permission_mode(run_id, payload.get("mode", "")))

    @app.post("/runs/{run_id}/resume", dependencies=[Depends(require_token)])
    async def resume_run(run_id: str) -> dict:
        """从持久态续跑被 kill/重启的 run（P3）；提交驱动，不直 reduce。"""
        return {"run_id": await server.resume(run_id)}

    @app.get("/events/{run_id}", dependencies=[Depends(require_token)])
    async def events(request: Request, run_id: str, after_seq: int = 0) -> EventSourceResponse:
        """SSE 事件流；优先用 ``Last-Event-ID`` 头作续传游标，并接住客户端契约版本闸门。"""
        header = request.headers.get("last-event-id")
        if header and header.isdigit():
            after_seq = int(header)
        version_header = request.headers.get("x-questor-contract-version")
        expected_version = int(version_header) if version_header and version_header.isdigit() else None
        return EventSourceResponse(server.stream(run_id, after_seq, expected_version=expected_version))

    # 静态前端（桌面壳的 webview 入口）：仅在给定且存在时挂载，挂载于所有 API 路由之后，
    # 故 /run·/events 等精确路由优先匹配，其余（含 /）走静态目录。
    if static_dir is not None and static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="web")

    return app
