"""L2 turn loop (design/04; HARD C7/C8/C10). P1 = single model, serial tools.

``DefaultTurnLoop`` drives one Run to a single terminal event. It is *pure
mechanism*: it never imports a concrete policy/tool/surface — those arrive
injected as ``contracts`` Ports/callbacks (C1/C14). Every state change goes
through ``reduce`` (single writer); deltas are emitted live and never persisted.

Scope guards honored (ROADMAP §2.5): serial tools only (``parallel_safe`` is a
schema placeholder), one model, cancel/deny/illegal-intent must not crash.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

from jsonschema import Draft202012Validator

from questor.contracts.common import JsonObject, new_id, utc_now
from questor.contracts.errors import ErrorEntry, ErrorKind, ErrorLayer, RecoveryHints
from questor.contracts.events import (
    AdvanceTurn,
    AppendAssistantMessage,
    Cancel,
    Envelope,
    EventType,
    FinalizeRun,
    MarkToolDenied,
    RecordToolResult,
    SubmitMessage,
)
from questor.contracts.policy import PolicyPort, PolicyView, ProposeToolCall, SuggestFinish
from questor.contracts.ports import ProviderPort, ProviderRequest
from questor.contracts.state_schema import (
    CancelReason,
    ContentBlock,
    Message,
    Role,
)
from questor.contracts.tool import Tool
from questor.kernel.events import EventBus
from questor.state.domain_state import Run
from questor.state.reduce import reduce

Approver = Callable[[str, JsonObject, str], Awaitable[bool]]


class _ToolCtx:
    """Concrete :class:`ToolContext` handed to a tool — controlled capabilities only."""

    def __init__(self, workspace_root: Path, cancel_event: asyncio.Event) -> None:
        self.workspace_root = workspace_root
        self._cancel = cancel_event

    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def report_progress(self, message: str) -> None:  # pragma: no cover - observability hook
        pass

    def emit_progress(self, payload: JsonObject) -> None:  # pragma: no cover - observability hook
        pass


class DefaultTurnLoop:
    def __init__(
        self,
        *,
        provider: ProviderPort,
        policy: PolicyPort,
        permission,
        bus: EventBus,
        tool_for: Callable[[str], Tool | None],
        tools: tuple[Tool, ...] = (),
        workspace_root: Path | None = None,
        model: str = "",
        system: str | None = None,
        approver: Approver | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        self.provider = provider
        self.policy = policy
        self.permission = permission
        self.bus = bus
        self.tool_for = tool_for
        self.tools = tools
        self.workspace_root = workspace_root or Path.cwd()
        self.model = model
        self.system = system
        self.approver = approver
        self.cancel_event = cancel_event or asyncio.Event()

    async def drive(self, run: Run, user_text: str) -> Run:
        user_msg = Message(id=new_id("msg"), role=Role.USER, content=(ContentBlock(type="text", text=user_text),), seq=len(run.context.items))
        run, events = reduce(run, SubmitMessage(run_id=run.run_id, content=user_msg))
        await self._emit(events)

        turn = 0
        while True:
            if self.cancel_event.is_set():
                run, events = reduce(run, Cancel(run_id=run.run_id, reason=CancelReason.USER))
                await self._emit(events)
                return run
            if run.status.is_terminal:
                return run

            turn += 1
            if turn > run.budget.max_turns:
                err = ErrorEntry(
                    kind=ErrorKind.TIMEOUT,
                    layer=ErrorLayer.KERNEL,
                    message=f"max_turns {run.budget.max_turns} exhausted",
                    at_turn=turn,
                    hints=RecoveryHints(),
                    timestamp=utc_now(),
                )
                run, events = reduce(run, FinalizeRun(run_id=run.run_id, status="failed", error=err, exit_reason="budget_exhausted"))
                await self._emit(events)
                return run

            run, events = reduce(run, AdvanceTurn(run_id=run.run_id, turn=turn))
            await self._emit(events)

            assistant_msg, usage = await self._stream_turn(run, turn)
            run, events = reduce(run, AppendAssistantMessage(run_id=run.run_id, turn=turn, message=assistant_msg))
            await self._emit(events)

            intent = self._ask_policy(run)
            if intent is None:  # policy panicked -> stay alive, ask provider again
                continue

            if isinstance(intent, SuggestFinish):
                final = assistant_msg if _has_text(assistant_msg) else None
                run, events = reduce(run, FinalizeRun(run_id=run.run_id, status="completed", final=final, usage=usage, exit_reason="answered"))
                await self._emit(events)
                return run

            if isinstance(intent, ProposeToolCall):
                run = await self._handle_tool_call(run, intent)

    # ---- phase helpers ----------------------------------------------------
    async def _stream_turn(self, run: Run, turn: int) -> tuple[Message, JsonObject]:
        request = ProviderRequest(model=self.model, messages=run.context.items, tools=tuple(t.spec for t in self.tools), system=self.system)
        text_parts: list[str] = []
        usage: JsonObject = {}
        calls: dict[int, dict] = {}
        async for chunk in self.provider.stream(request):
            if chunk.kind == "text" and chunk.text:
                text_parts.append(chunk.text)
                await self._live(run, turn, EventType.TEXT_DELTA, {"delta": chunk.text})
            elif chunk.kind == "reasoning" and chunk.text:
                await self._live(run, turn, EventType.REASONING_DELTA, {"delta": chunk.text})
            elif chunk.kind == "tool_call" and chunk.tool_call:
                slot = calls.setdefault(chunk.tool_call["index"], {"id": None, "name": "", "args": ""})
                if chunk.tool_call.get("id"):
                    slot["id"] = chunk.tool_call["id"]
                if chunk.tool_call.get("name"):
                    slot["name"] = chunk.tool_call["name"]
                slot["args"] += chunk.tool_call.get("args_delta") or ""
            elif chunk.kind == "usage" and chunk.usage:
                usage = dict(chunk.usage)
        blocks: list[ContentBlock] = []
        if text_parts:
            blocks.append(ContentBlock(type="text", text="".join(text_parts)))
        for index in sorted(calls):
            slot = calls[index]
            blocks.append(ContentBlock(type="tool_use", tool_use_id=slot["id"] or new_id("tc"), name=slot["name"], input=_parse_args(slot["args"])))
        msg = Message(id=new_id("msg"), role=Role.ASSISTANT, content=tuple(blocks), seq=len(run.context.items))
        return msg, usage

    def _ask_policy(self, run: Run):
        view = PolicyView(context=run.context.items, tool_results=run.tool_ledger.calls, tools=tuple(t.spec for t in self.tools), budget=run.budget)
        try:
            return self.policy.propose_action(view)
        except Exception:  # X4: isolate strategy faults, never crash the run
            return None

    async def _handle_tool_call(self, run: Run, intent: ProposeToolCall) -> Run:
        tool = self.tool_for(intent.name)
        if tool is None:
            run, events = reduce(run, RecordToolResult(run_id=run.run_id, tool_call_id=intent.tool_call_id or "", status="error", result=f"unknown tool '{intent.name}'"))
            await self._emit(events)
            return run

        decision, reason = self.permission.evaluate(intent.name, intent.args)
        if decision == "deny":
            run, events = reduce(run, MarkToolDenied(run_id=run.run_id, tool_call_id=intent.tool_call_id or "", reason=reason))
            await self._emit(events)
            return run
        if decision == "ask":
            allowed = bool(self.approver) and await self.approver(intent.name, intent.args, reason)
            if not allowed:
                run, events = reduce(run, MarkToolDenied(run_id=run.run_id, tool_call_id=intent.tool_call_id or "", reason="denied by approver"))
                await self._emit(events)
                return run

        error = _schema_error(tool.spec.params, intent.args)
        if error is not None:
            run, events = reduce(run, RecordToolResult(run_id=run.run_id, tool_call_id=intent.tool_call_id or "", status="error", result=error))
            await self._emit(events)
            return run

        ctx = _ToolCtx(self.workspace_root, self.cancel_event)
        result = await tool.execute(intent.args, ctx)
        run, events = reduce(run, RecordToolResult(run_id=run.run_id, tool_call_id=intent.tool_call_id or "", status=result.status, result=result.result, display=result.display))
        await self._emit(events)
        return run

    async def _emit(self, events: list[Envelope]) -> None:
        for env in events:
            await self.bus.emit(env)

    async def _live(self, run: Run, turn: int, etype: str, data: dict) -> None:
        # live-only deltas: forwarded to subscribers, never persisted (design/01 I3).
        await self.bus.emit(Envelope(v=1, seq=run.seq, run_id=run.run_id, type=etype, turn=turn, data=data))


def _has_text(message: Message) -> bool:
    return any(b.type == "text" and b.text for b in message.content)


def _parse_args(raw: str) -> JsonObject:
    import json

    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}


def _schema_error(params: JsonObject, args: JsonObject) -> str | None:
    validator = Draft202012Validator(params)
    errs = sorted(validator.iter_errors(args), key=lambda e: e.path)
    if not errs:
        return None
    return "invalid arguments: " + "; ".join(e.message for e in errs[:3])
