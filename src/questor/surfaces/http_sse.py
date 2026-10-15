"""L6 HTTP + SSE 事件服务（ADR-0007；design/02 §4）。P1 T10。

零业务逻辑（STRUCTURE S6）：端点只把 Command*提交*进 loop、把事件流*投影*成 SSE。
续传是一等能力：``GET /events/{run_id}`` 遵从 ``Last-Event-ID``/``after_seq``，先经 store
重放 durable 尾、再跟实时，每帧带 ``id: <seq>``。

SSE 帧/头风格改形自 CowAgent ``openai_compat.py``；``id:<seq>`` + after_seq 重放接线为本仓
自写（两个参考都未暴露它——R10 §⑤）。"""

from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, Request
from sse_starlette.sse import EventSourceResponse

from questor.contracts.common import new_id, thaw
from questor.contracts.events import Envelope, EventType
from questor.contracts.state_schema import Budget
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import Run
from questor.surfaces.cli import CliSurface

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
    """持有端点共享的 store + bus + 在飞 run 的取消位。"""

    def __init__(self, surface: CliSurface, store: SQLiteStore) -> None:
        self.surface = surface
        self.store = store
        self.bus = InProcessEventBus(store)
        self._cancels: dict[str, asyncio.Event] = {}

    def _loop(self, run_id: str, cancel: asyncio.Event) -> DefaultTurnLoop:
        """复用 surface 的装配，但挂到本服务共享的 bus 上。"""
        return self.surface._loop(self.bus, cancel)

    async def start_run(self, text: str, run_id: str | None = None) -> str:
        """后台启动一次 run，立即返回 run_id（事件经 /events 拉取）。"""
        run_id = run_id or new_id("run")
        cancel = asyncio.Event()
        self._cancels[run_id] = cancel
        run = Run(run_id=run_id, budget=Budget())
        asyncio.create_task(self._loop(run_id, cancel).drive(run, text))
        return run_id

    def cancel(self, run_id: str) -> None:
        """置该 run 的取消位；loop 在下一个安全点经 Cancel Command 收尾。"""
        event = self._cancels.get(run_id)
        if event is not None:
            event.set()

    async def stream(self, run_id: str, after_seq: int = 0):
        """产出 SSE 帧：先重放 after_seq 之后、再跟实时，至终态停并清理取消位。"""
        async for env in self.bus.subscribe(run_id, after_seq):
            yield envelope_to_frame(env)
            if env.type in TERMINAL:
                self._cancels.pop(run_id, None)
                return


def create_app(server: EventServer) -> FastAPI:
    """构建 FastAPI 应用：``/run``、``/cancel/{run_id}``、``/events/{run_id}``。"""
    app = FastAPI(title="questor", version="0.1.0")

    @app.post("/run")
    async def run(payload: dict) -> dict:
        """受理一轮：后台起 run，返回 run_id。"""
        run_id = await server.start_run(payload.get("text", ""), payload.get("run_id"))
        return {"run_id": run_id}

    @app.post("/cancel/{run_id}")
    async def cancel(run_id: str) -> dict:
        """请求取消某 run。"""
        server.cancel(run_id)
        return {"cancelled": run_id}

    @app.get("/events/{run_id}")
    async def events(request: Request, run_id: str, after_seq: int = 0) -> EventSourceResponse:
        """SSE 事件流；优先用 ``Last-Event-ID`` 头作续传游标。"""
        header = request.headers.get("last-event-id")
        if header and header.isdigit():
            after_seq = int(header)
        return EventSourceResponse(server.stream(run_id, after_seq))

    return app
