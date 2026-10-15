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
import json
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from jsonschema import Draft202012Validator

from questor.contracts.common import JsonObject, new_id, thaw, utc_now
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
from questor.contracts.ports import ProviderPort, ProviderRequest, SandboxPort, StorePort
from questor.contracts.state_schema import (
    OPEN_TOOL_CALL_STATUSES,
    CancelReason,
    ContentBlock,
    Message,
    Role,
)
from questor.contracts.tool import Capability, Risk, Tool
from questor.kernel.events import EventBus
from questor.state.checkpoint import open_tool_use_ids
from questor.state.domain_state import Run
from questor.state.reduce import reduce
from questor.state.snapshot import to_snapshot

Approver = Callable[[str, JsonObject, str], Awaitable[bool]]

#: capabilities that MUST be sandboxed; with no capable backend they are denied
#: (fail-closed, design/03 §10 T4 — "degrade = safer, not looser").
_SANDBOXED_CAPABILITIES = frozenset({Capability.EXEC, Capability.WRITE, Capability.NETWORK})


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
        sandbox: SandboxPort | None = None,
        store: StorePort | None = None,
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
        self.sandbox = sandbox
        self.store = store
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
        started = time.monotonic()
        total_tokens = 0
        faults = 0
        repeat_sig: tuple | None = None
        repeat_count = 0
        empties = 0
        while True:
            if self.cancel_event.is_set():
                run, events = reduce(run, Cancel(run_id=run.run_id, reason=CancelReason.USER))
                await self._emit(events)
                return run
            if run.status.is_terminal:
                return run
            if run.budget.deadline_seconds is not None and (time.monotonic() - started) > run.budget.deadline_seconds:
                return await self._fail(run, turn, ErrorKind.TIMEOUT, f"wall-clock deadline {run.budget.deadline_seconds}s exceeded", "deadline")

            turn += 1
            if turn > run.budget.max_turns:
                return await self._fail(run, turn, ErrorKind.TIMEOUT, f"max_turns {run.budget.max_turns} exhausted", "budget_exhausted")

            turn_start = run  # C10/X4 rollback point: state at the start of this turn
            run, events = reduce(run, AdvanceTurn(run_id=run.run_id, turn=turn))
            await self._emit(events)

            assistant_msg, usage = await self._stream_turn(run, turn)
            total_tokens += _token_total(usage)
            run, events = reduce(run, AppendAssistantMessage(run_id=run.run_id, turn=turn, message=assistant_msg))
            await self._emit(events)
            await self._checkpoint(run, "auto")

            if run.budget.max_tokens is not None and total_tokens > run.budget.max_tokens:
                return await self._fail(run, turn, ErrorKind.INTERNAL, f"token budget {run.budget.max_tokens} exceeded (used {total_tokens})", "budget_exhausted")

            has_text = _has_text(assistant_msg)
            has_tool = any(b.type == "tool_use" for b in assistant_msg.content)
            if not has_text and not has_tool:  # provider kept "continuing" with empty answers
                empties += 1
                if empties > run.budget.max_consecutive_continuations:
                    return await self._fail(run, turn, ErrorKind.INTERNAL, "repeated empty answers (no text/tool)", "no_progress")
            else:
                empties = 0

            intent, faulted = self._ask_policy(run)
            if faulted:
                faults += 1
                await self._live(run, turn, EventType.WARNING, {"message": "policy raised; rolling back turn (C10)"})
                run = turn_start  # restore Domain_State to turn start; already-emitted deltas are not withdrawn
                if faults > 2:
                    return await self._fail(run, turn, ErrorKind.POLICY_VIOLATION, "policy raised repeatedly", "policy_error")
                continue
            faults = 0

            if isinstance(intent, SuggestFinish):
                if any(c.status in OPEN_TOOL_CALL_STATUSES for c in run.tool_ledger.calls):
                    continue  # stop-gate: reject premature Finish while tool calls are still open
                final = assistant_msg if has_text else None
                run, events = reduce(run, FinalizeRun(run_id=run.run_id, status="completed", final=final, usage=usage, exit_reason="answered"))
                await self._emit(events)
                return run

            if isinstance(intent, ProposeToolCall):
                sig = (intent.name, str(thaw(intent.args)))
                repeat_count = repeat_count + 1 if sig == repeat_sig else 1
                repeat_sig = sig
                if repeat_count > run.budget.repeat_tool_limit:
                    return await self._fail(run, turn, ErrorKind.INTERNAL, f"repeated identical tool call '{intent.name}' x{repeat_count}", "no_progress")
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

    async def _fail(self, run: Run, turn: int, kind: ErrorKind, message: str, exit_reason: str) -> Run:
        err = ErrorEntry(kind=kind, layer=ErrorLayer.KERNEL, message=message, at_turn=turn, hints=RecoveryHints(), timestamp=utc_now())
        run, events = reduce(run, FinalizeRun(run_id=run.run_id, status="failed", error=err, exit_reason=exit_reason))
        await self._emit(events)
        return run

    async def _checkpoint(self, run: Run, kind: str) -> None:
        """Persist a turn-boundary snapshot for recovery (A1). No-op without a store."""
        if self.store is None:
            return
        await self.store.save_checkpoint(
            {
                "cp_id": new_id("cp"),
                "run_id": run.run_id,
                "seq": run.seq,
                "turn": run.turn,
                "kind": kind,
                "state_digest": json.dumps(to_snapshot(run), ensure_ascii=False, default=str),
                "pending": list(open_tool_use_ids(run.context.items)),
            }
        )

    def _ask_policy(self, run: Run) -> tuple[object, bool]:
        """Return ``(intent, faulted)``; a strategy exception is isolated (X4), never crashes the run."""
        view = PolicyView(context=run.context.items, tool_results=run.tool_ledger.calls, tools=tuple(t.spec for t in self.tools), budget=run.budget)
        try:
            return self.policy.propose_action(view), False
        except Exception:  # noqa: BLE001 - strategy faults must not break the loop
            return None, True

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

        # Capability/risk fail-closed gate: a sandboxed capability with no capable
        # backend is DENIED rather than run raw (03 §10 T4; C9). Runs after the
        # permission decision so we never downgrade an explicit allow to execute.
        deny_reason = self._sandbox_denial(tool)
        if deny_reason is not None:
            run, events = reduce(run, MarkToolDenied(run_id=run.run_id, tool_call_id=intent.tool_call_id or "", reason=deny_reason))
            await self._emit(events)
            return run

        ctx = _ToolCtx(self.workspace_root, self.cancel_event)
        result = await tool.execute(intent.args, ctx)
        run, events = reduce(run, RecordToolResult(run_id=run.run_id, tool_call_id=intent.tool_call_id or "", status=result.status, result=result.result, display=result.display))
        await self._emit(events)
        return run

    def _sandbox_denial(self, tool: Tool) -> str | None:
        """Return a deny reason when the tool needs isolation the backend can't give."""
        spec = tool.spec
        needs = spec.capability in _SANDBOXED_CAPABILITIES or spec.risk is Risk.HIGH
        if not needs:
            return None
        if self.sandbox is None:
            return f"no sandbox backend available for {spec.capability.value}/{spec.risk.value} tool (fail-closed)"
        if spec.capability is Capability.WRITE and not self.sandbox.fences_writes():
            return "sandbox cannot fence writes for a write tool (fail-closed)"
        if spec.capability is Capability.NETWORK and not self.sandbox.fences_network():
            return "sandbox cannot fence network for a network tool (fail-closed)"
        if spec.capability is Capability.EXEC and not self.sandbox.isolates_process_tree():
            return "sandbox cannot isolate the process tree for an exec tool (fail-closed)"
        return None

    async def _emit(self, events: list[Envelope]) -> None:
        for env in events:
            await self.bus.emit(env)

    async def _live(self, run: Run, turn: int, etype: str, data: dict) -> None:
        # live-only deltas: forwarded to subscribers, never persisted (design/01 I3).
        await self.bus.emit(Envelope(v=1, seq=run.seq, run_id=run.run_id, type=etype, turn=turn, data=data))


def _has_text(message: Message) -> bool:
    return any(b.type == "text" and b.text for b in message.content)


def _token_total(usage: JsonObject) -> int:
    for key in ("total_tokens", "completion_tokens", "output_tokens"):
        value = usage.get(key)
        if value:
            try:
                return int(value)
            except (TypeError, ValueError):
                return 0
    return 0


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
