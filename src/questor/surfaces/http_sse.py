"""L6 HTTP + SSE event service (ADR-0007; design/02 §4). P1 T10.

Zero business logic (STRUCTURE S6): the endpoints only *submit* Commands into the
loop and *project* the event stream out over SSE. Resume is first-class:
``GET /events/{run_id}`` honors ``Last-Event-ID``/``after_seq`` and replays the
durable tail (via the store) before following live, each frame tagged ``id: <seq>``.

SSE frame/headers style adapts CowAgent ``openai_compat.py``; the ``id:<seq>`` +
after_seq replay wiring is our own (neither reference exposed it — R10 §⑤).
"""

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

TERMINAL = {EventType.RUN_COMPLETED, EventType.RUN_CANCELLED, EventType.RUN_FAILED}


def envelope_to_json(env: Envelope) -> str:
    return json.dumps(
        {"v": env.v, "seq": env.seq, "run_id": env.run_id, "turn": env.turn, "ts": env.ts.isoformat(), "type": env.type, "data": thaw(env.data)},
        ensure_ascii=False,
        default=str,
    )


def envelope_to_frame(env: Envelope) -> dict:
    """SSE frame: leading ``id: <seq>`` for resume + the JSON envelope as data."""
    return {"id": str(env.seq), "event": env.type, "data": envelope_to_json(env)}


class EventServer:
    """Owns the shared store + bus + in-flight runs the endpoints drive."""

    def __init__(self, surface: CliSurface, store: SQLiteStore) -> None:
        self.surface = surface
        self.store = store
        self.bus = InProcessEventBus(store)
        self._cancels: dict[str, asyncio.Event] = {}

    def _loop(self, run_id: str, cancel: asyncio.Event) -> DefaultTurnLoop:
        return self.surface._loop(self.bus, cancel)

    async def start_run(self, text: str, run_id: str | None = None) -> str:
        run_id = run_id or new_id("run")
        cancel = asyncio.Event()
        self._cancels[run_id] = cancel
        run = Run(run_id=run_id, budget=Budget())
        asyncio.create_task(self._loop(run_id, cancel).drive(run, text))
        return run_id

    def cancel(self, run_id: str) -> None:
        event = self._cancels.get(run_id)
        if event is not None:
            event.set()

    async def stream(self, run_id: str, after_seq: int = 0):
        async for env in self.bus.subscribe(run_id, after_seq):
            yield envelope_to_frame(env)
            if env.type in TERMINAL:
                self._cancels.pop(run_id, None)
                return


def create_app(server: EventServer) -> FastAPI:
    app = FastAPI(title="questor", version="0.1.0")

    @app.post("/run")
    async def run(payload: dict) -> dict:
        run_id = await server.start_run(payload.get("text", ""), payload.get("run_id"))
        return {"run_id": run_id}

    @app.post("/cancel/{run_id}")
    async def cancel(run_id: str) -> dict:
        server.cancel(run_id)
        return {"cancelled": run_id}

    @app.get("/events/{run_id}")
    async def events(request: Request, run_id: str, after_seq: int = 0) -> EventSourceResponse:
        header = request.headers.get("last-event-id")
        if header and header.isdigit():
            after_seq = int(header)
        return EventSourceResponse(server.stream(run_id, after_seq))

    return app
