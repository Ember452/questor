"""L2 turn 循环（design/04；HARD C7/C8/C10）。P1 = 单模型、串行工具。

``DefaultTurnLoop`` 把一次 Run 驱动到唯一终态。它是*纯机制*：从不 import 具体
策略/工具/传输面——那些以 ``contracts`` 的 Port/回调注入（C1/C14）。所有状态变更走
``reduce``（单写者）；delta 直发事件流、永不落库。

恪守的 phase 范围（ROADMAP §2.5）：仅串行工具（``parallel_safe`` 只是 schema 占位）、
单模型，且取消/deny/非法意图三条路径绝不得崩。
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
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
    ExpireApproval,
    FinalizeRun,
    MarkToolDenied,
    MarkToolRunning,
    MarkToolValidated,
    RecordToolResult,
    RequestApproval,
    ResolveApproval,
    SubmitMessage,
)
from questor.contracts.policy import PolicyPort, PolicyView, ProposeToolCall, SuggestFinish
from questor.contracts.ports import ProviderPort, ProviderRequest, SandboxPort, StorePort
from questor.contracts.sandbox import Confinement, SandboxBackend, SandboxDescriptor
from questor.contracts.shell_analysis import ShellAnalysis, ShellDialect, ShellParseStatus
from questor.contracts.state_schema import (
    OPEN_TOOL_CALL_STATUSES,
    CancelReason,
    ContentBlock,
    Message,
    Role,
    ToolArgsStatus,
    ToolCallStatus,
)
from questor.contracts.tool import RunToolSurface, Tool, ToolResult, ToolSpec
from questor.kernel.events import EventBus
from questor.kernel.permission_policy import PermissionDecision, PermissionEvaluation
from questor.kernel.run_control import RunController
from questor.kernel.shell_parse_posix import parse_posix_shell
from questor.kernel.shell_parse_powershell import parse_powershell
from questor.kernel.tool_arguments import extract_shell_commands
from questor.state.checkpoint import open_tool_use_ids
from questor.state.domain_state import Run
from questor.state.reduce import reduce
from questor.state.snapshot import to_snapshot


class _ToolCtx:
    """交给工具的具体 :class:`ToolContext`——只暴露受控能力。"""

    def __init__(
        self,
        workspace_root: Path,
        cancel_event: asyncio.Event,
        *,
        tool_call_id: str = "",
        cwd: Path | None = None,
        run_id: str = "",
        process_runner: object | None = None,
        artifact_store: object | None = None,
    ) -> None:
        self.workspace_root = workspace_root
        self.cwd = cwd or workspace_root
        self.tool_call_id = tool_call_id
        self.run_id = run_id
        self._process_runner = process_runner
        self._artifact_store = artifact_store
        self._cancel = cancel_event
        # T11/T12 前只记录声明；真正的 ProcessRunner 必须读取此列表并执行 provider credential 过滤。
        self._declared_env_names: set[str] = set()

    def is_cancelled(self) -> bool:
        """供长任务轮询的安全取消点。"""
        return self._cancel.is_set()

    def report_progress(self, message: str) -> None:  # pragma: no cover - 观测钩子
        pass

    def emit_progress(self, payload: JsonObject) -> None:  # pragma: no cover - 观测钩子
        pass

    def declare_env_passthrough(self, name: str) -> None:
        """记录工具显式请求的环境变量名；值不在此保存（ADR-0018）。"""
        self._declared_env_names.add(name)

    async def run_process(self, request: object) -> object:
        """把工具的结构化进程请求交给 Harness-owned runner（合并已声明 env 名）。

        未接入 runner 时报错（不默默 spawn）：capability 层绝不自持 spawn 能力（C1/C8）。
        """
        if self._process_runner is None:
            raise RuntimeError("no ProcessRunner wired into ToolContext")
        merged = replace(request, declared_env_names=tuple(dict.fromkeys((*request.declared_env_names, *self._declared_env_names))))  # type: ignore[attr-defined]
        return await self._process_runner.run(merged)

    async def put_artifact(
        self,
        content: bytes,
        *,
        kind: str,
        media_type: str = "text/plain",
    ) -> object:
        """把工具全文输出交给 ArtifactStore（内容寻址、路径不由工具拼接）。"""
        if self._artifact_store is None:
            raise RuntimeError("no ArtifactStore wired into ToolContext")
        return await self._artifact_store.put_bytes(content, run_id=self.run_id, kind=kind, media_type=media_type)


def _none_descriptor() -> SandboxDescriptor:
    return SandboxDescriptor(
        backend=SandboxBackend.NONE,
        confinement=Confinement.NONE,
        fences_writes=False,
        fences_network=False,
        isolates_process_tree=False,
        limitation="no sandbox backend available",
    )


def _analyze_shell(tool_spec: ToolSpec, arguments: JsonObject) -> ShellAnalysis | None:
    """只按 ToolSpec capability/name 选 dialect；不靠工具名字符串猜安全。"""
    commands = extract_shell_commands(arguments)
    if not commands:
        return None
    powershell = tool_spec.name.lower() in {"powershell", "pwsh"}
    analyses = [parse_powershell(command) if powershell else parse_posix_shell(command) for command in commands]
    if any(analysis.status is not ShellParseStatus.PARSED for analysis in analyses):
        return analyses[0]
    segments = tuple(segment for analysis in analyses for segment in analysis.segments)
    dialect = ShellDialect.POWERSHELL if powershell else ShellDialect.POSIX
    read_paths = tuple(dict.fromkeys(path for analysis in analyses for path in analysis.read_paths))
    write_paths = tuple(dict.fromkeys(path for analysis in analyses for path in analysis.write_paths))
    return ShellAnalysis(
        dialect=dialect,
        status=ShellParseStatus.PARSED,
        segments=segments,
        read_paths=read_paths,
        write_paths=write_paths,
    )


class DefaultTurnLoop:
    """P1 内核循环：用注入的 provider/policy/permission/tools/bus/store 驱动 phase pipeline。"""

    def __init__(
        self,
        *,
        provider: ProviderPort,
        policy: PolicyPort,
        permission,
        bus: EventBus,
        tool_for: Callable[[str], Tool | None],
        tools: tuple[Tool, ...] = (),
        surface: RunToolSurface | None = None,
        sandbox: SandboxPort | None = None,
        process_runner: object | None = None,
        artifact_store: object | None = None,
        store: StorePort | None = None,
        workspace_root: Path | None = None,
        model: str = "",
        system: str | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        self.provider = provider
        self.policy = policy
        self.permission = permission
        self.bus = bus
        self.tool_for = tool_for
        self.tools = tools
        self.surface = surface
        self.sandbox = sandbox
        self.process_runner = process_runner
        self.artifact_store = artifact_store
        self.store = store
        self.workspace_root = workspace_root or Path.cwd()
        self.model = model
        self.system = system
        self.cancel_event = cancel_event or asyncio.Event()

    def _tool(self, name: str) -> Tool | None:
        """工具解析优先走冻结 surface（run 内工具面不变），否则走兼容入口。"""
        if self.surface is not None:
            return self.surface.tool_for(name)
        return self.tool_for(name)

    def _specs(self) -> tuple[ToolSpec, ...]:
        if self.surface is not None:
            return self.surface.specs
        return tuple(t.spec for t in self.tools)

    async def drive(self, run: Run, user_text: str) -> Run:
        """兼容 P1 入口：把 user text 也经 RunController，绝不在 loop 外偷偷 reduce。"""
        controller = RunController(run)
        user_msg = Message(id=new_id("msg"), role=Role.USER, content=(ContentBlock(type="text", text=user_text),), seq=len(run.context.items))
        await controller.submit(
            SubmitMessage(run_id=run.run_id, content=user_msg),
            source="legacy-drive",
            idempotency_key=f"submit:{run.run_id}",
        )
        return await self.drive_controller(controller)

    async def drive_controller(self, controller: RunController) -> Run:
        """RunController 是 Command 的唯一串行入口；终态后关闭迟到写入。"""
        try:
            result = await self._drive_controller(controller)
            controller.run = result
            return result
        finally:
            if controller.run.status.is_terminal:
                controller.close()

    async def _drive_controller(self, controller: RunController) -> Run:
        """驱动 controller 当前 Run 到唯一终态；Command 仅在安全点消费。"""
        run = controller.run
        # resume：若从快照重建出仍有未闭合 tool_use（崩溃 mid-dispatch / 审批挂起），先在同一
        # 安全点补齐或等待，再进入 provider-first 循环——否则会把半截 tool_use 喂回 provider
        # （Anthropic/OpenAI 强制成对，直接 4xx）。新鲜 run 无 open 调用，此处即空操作（ADR-0021）。
        run = await self._resume_settle_open_calls(controller, run)
        turn = run.turn
        started = time.monotonic()
        total_tokens = 0
        faults = 0
        repeat_sig: tuple | None = None
        repeat_count = 0
        empties = 0
        while True:
            run = await self._consume_commands(controller, run)
            if run.status.is_terminal:
                return run
            if self.cancel_event.is_set():
                run, events = reduce(run, Cancel(run_id=run.run_id, reason=CancelReason.USER))
                controller.run = run
                await self._emit(events)
                return run
            if run.budget.deadline_seconds is not None and (time.monotonic() - started) > run.budget.deadline_seconds:
                return await self._fail(run, turn, ErrorKind.TIMEOUT, f"wall-clock deadline {run.budget.deadline_seconds}s exceeded", "deadline")

            turn += 1
            if turn > run.budget.max_turns:
                return await self._fail(run, turn, ErrorKind.TIMEOUT, f"max_turns {run.budget.max_turns} exhausted", "budget_exhausted")

            turn_start = run  # C10/X4 回滚点：本 turn 起始时的状态
            run, events = reduce(run, AdvanceTurn(run_id=run.run_id, turn=turn))
            controller.run = run
            await self._emit(events)

            assistant_msg, usage = await self._stream_turn(run, turn)
            total_tokens += _token_total(usage)
            run, events = reduce(run, AppendAssistantMessage(run_id=run.run_id, turn=turn, message=assistant_msg))
            controller.run = run
            await self._emit(events)
            await self._checkpoint(run, "auto")

            if run.budget.max_tokens is not None and total_tokens > run.budget.max_tokens:
                return await self._fail(run, turn, ErrorKind.INTERNAL, f"token budget {run.budget.max_tokens} exceeded (used {total_tokens})", "budget_exhausted")

            has_text = _has_text(assistant_msg)
            has_tool = any(b.type == "tool_use" for b in assistant_msg.content)
            if not has_text and not has_tool:  # provider 连续“续跑”却返回空答
                empties += 1
                if empties > run.budget.max_consecutive_continuations:
                    return await self._fail(run, turn, ErrorKind.INTERNAL, "repeated empty answers (no text/tool)", "no_progress")
            else:
                empties = 0

            intent, faulted = self._ask_policy(run)
            if faulted:
                faults += 1
                await self._live(run, turn, EventType.WARNING, {"message": "policy raised; rolling back turn (C10)"})
                run = turn_start  # 回滚 Domain_State 到 turn 起点；已发出的 delta 不撤销
                if faults > 2:
                    return await self._fail(run, turn, ErrorKind.POLICY_VIOLATION, "policy raised repeatedly", "policy_error")
                continue
            faults = 0

            if isinstance(intent, SuggestFinish):
                if any(c.status in OPEN_TOOL_CALL_STATUSES for c in run.tool_ledger.calls):
                    continue  # stop-gate：尚有未闭合工具调用时拒绝过早 Finish
                final = assistant_msg if has_text else None
                run, events = reduce(run, FinalizeRun(run_id=run.run_id, status="completed", final=final, usage=usage, exit_reason="answered"))
                controller.run = run
                await self._emit(events)
                return run

            if isinstance(intent, ProposeToolCall):
                sig = (intent.name, str(thaw(intent.args)))
                repeat_count = repeat_count + 1 if sig == repeat_sig else 1
                repeat_sig = sig
                if repeat_count > run.budget.repeat_tool_limit:
                    return await self._fail(run, turn, ErrorKind.INTERNAL, f"repeated identical tool call '{intent.name}' x{repeat_count}", "no_progress")
                run = await self._handle_tool_call(controller, run, intent)

    async def _consume_commands(self, controller: RunController, run: Run) -> Run:
        """按 FIFO 应用 inbox 中已到达的 Command；reduce 只在此处由 loop 调用。"""
        for command in await controller.next_batch():
            run, events = reduce(run, command)
            controller.run = run
            await self._emit(events)
            if run.status.is_terminal:
                return run
        return run

    # ---- phase 辅助方法 ------------------------------------------------
    async def _stream_turn(self, run: Run, turn: int) -> tuple[Message, JsonObject]:
        """跑一轮流式：逐块 emit live delta、累积文本/工具参/用量，定稿为一条 assistant 消息。"""
        request = ProviderRequest(model=self.model, messages=run.context.items, tools=self._specs(), system=self.system)
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
            blocks.append(_finish_tool_use(index, calls[index]))
        msg = Message(id=new_id("msg"), role=Role.ASSISTANT, content=tuple(blocks), seq=len(run.context.items))
        return msg, usage

    async def _fail(self, run: Run, turn: int, kind: ErrorKind, message: str, exit_reason: str) -> Run:
        """以 failed 终态优雅收尾（归一化 ErrorEntry 入栈）。"""
        err = ErrorEntry(kind=kind, layer=ErrorLayer.KERNEL, message=message, at_turn=turn, hints=RecoveryHints(), timestamp=utc_now())
        run, events = reduce(run, FinalizeRun(run_id=run.run_id, status="failed", error=err, exit_reason=exit_reason))
        await self._emit(events)
        return run

    async def _checkpoint(self, run: Run, kind: str) -> None:
        """落一个稳态快照供恢复（A1）。无 store 时为空操作。

        ``state_digest`` 是权威状态（含完整 ToolCall 账本）；``pending`` 存未闭合 tool_use id，
        **仅供可观测/诊断用**——rebuild 的权威回退仍靠 ``state_digest`` 里的 ledger（不依赖此列），
        它是“崩溃→重派窗口”的审计标记（A3）。
        """
        if self.store is None:
            return
        await self.store.save_checkpoint(
            {
                "cp_id": new_id("cp"),
                "run_id": run.run_id,
                "seq": run.seq,
                "turn": run.turn,
                "kind": kind,
                "state_digest": json.dumps(to_snapshot(run), ensure_ascii=False, default=str, allow_nan=False),
                "pending": list(open_tool_use_ids(run.context.items)),
            }
        )

    def _ask_policy(self, run: Run) -> tuple[object, bool]:
        """返回 ``(intent, faulted)``；策略异常被隔离（X4），绝不崩整个 run。"""
        view = PolicyView(context=run.context.items, tool_results=run.tool_ledger.calls, tools=self._specs(), budget=run.budget)
        try:
            return self.policy.propose_action(view), False
        except Exception:  # noqa: BLE001 - 策略故障绝不得打断循环
            return None, True

    async def _handle_tool_call(self, controller: RunController, run: Run, intent: ProposeToolCall) -> Run:
        """工具路由：args→schema→validated→permission→sandbox→execute。"""
        call = next((c for c in run.tool_ledger.calls if c.tool_call_id == intent.tool_call_id), None)
        if call is None:
            run, events = reduce(run, RecordToolResult(run_id=run.run_id, tool_call_id=intent.tool_call_id or "", status="error", result="missing tool_use ledger entry"))
            controller.run = run
            await self._emit(events)
            return run
        if call.args_status is not ToolArgsStatus.VALID:
            reason = call.permission_reason or "invalid or missing tool arguments"
            run, events = reduce(run, RecordToolResult(run_id=run.run_id, tool_call_id=intent.tool_call_id or "", status="error", result=f"invalid json arguments: {reason}"))
            controller.run = run
            await self._emit(events)
            return run

        tool = self._tool(intent.name)
        if tool is None:
            run, events = reduce(run, RecordToolResult(run_id=run.run_id, tool_call_id=intent.tool_call_id or "", status="error", result=_unknown_tool_message(intent.name, self._specs(), self.surface)))
            controller.run = run
            await self._emit(events)
            return run

        error = _schema_error(tool.spec.params, intent.args)
        if error is not None:
            run, events = reduce(run, RecordToolResult(run_id=run.run_id, tool_call_id=intent.tool_call_id or "", status="error", result=error))
            controller.run = run
            await self._emit(events)
            return run

        run = await self._apply_command(controller, run, MarkToolValidated(run_id=run.run_id, tool_call_id=intent.tool_call_id or ""))
        analysis = _analyze_shell(tool.spec, intent.args)
        permission = replace(run.permission_ctx, workspace_root=str(self.workspace_root), cwd=str(self.workspace_root))
        sandbox_descriptor = self.sandbox.describe() if self.sandbox is not None and hasattr(self.sandbox, "describe") else _none_descriptor()
        outcome = self.permission.evaluate(
            PermissionEvaluation(
                tool_name=intent.name,
                tool_spec=tool.spec,
                args_status=call.args_status,
                arguments=intent.args,
                permission=permission,
                sandbox=sandbox_descriptor,
                shell_analysis=analysis,
            )
        )
        decision = outcome.decision
        reason = outcome.reason
        if decision is PermissionDecision.DENY:
            run = await self._apply_command(controller, run, MarkToolDenied(run_id=run.run_id, tool_call_id=intent.tool_call_id or "", reason=reason))
            return run
        if decision is PermissionDecision.ASK:
            run = await self._handle_ask(controller, run, tool, intent, outcome)
            call = next(c for c in run.tool_ledger.calls if c.tool_call_id == intent.tool_call_id)
            if call.status in {ToolCallStatus.DENIED, ToolCallStatus.CANCELLED} or run.status.is_terminal:
                return run
            if call.status is not ToolCallStatus.RUNNING:
                run = await self._apply_command(
                    controller,
                    run,
                    MarkToolRunning(
                        run_id=run.run_id,
                        tool_call_id=intent.tool_call_id or "",
                        capability=tool.spec.capability.value,
                        risk=tool.spec.risk.value,
                        timeout_s=tool.spec.timeout_s or run.budget.tool_default_timeout_seconds,
                    ),
                )
        else:
            run = await self._apply_command(
                controller,
                run,
                MarkToolRunning(
                    run_id=run.run_id,
                    tool_call_id=intent.tool_call_id or "",
                    capability=tool.spec.capability.value,
                    risk=tool.spec.risk.value,
                    timeout_s=tool.spec.timeout_s or run.budget.tool_default_timeout_seconds,
                ),
            )

        # 工具是插件（C10）：它的 panic 与挂死都必须由 Harness 兜住，否则单写者循环会崩、
        # tool_call 悬在 RUNNING 并留下无 tool_result 的配对破坏（I1/C7）。执行/配对/有界输出
        # 统一交给 _execute_tool（普通 turn 与 resume 重派共用，design/03 §8 deadline 对所有工具生效）。
        return await self._execute_tool(controller, run, tool, intent.tool_call_id or "", intent.args, intent.name)

    async def _execute_tool(self, controller: RunController, run: Run, tool: Tool, tool_call_id: str, args: object, name: str) -> Run:
        """执行工具并 settle 一条耐久结果（Harness 兜 panic/deadline，design/03 §8/C10）。

        普通 turn（``_handle_tool_call``）与 resume 重派（``_resume_execute_call``）共用：先经 ctx
        执行、deadline/panic 转结构化 error，再经 ``RecordToolResult`` 闭合配对、落 post_tool
        checkpoint（ADR-0020/0021：先 append 耐久事件再写快照，把"崩溃→重跑一个工具"的窗口收到最小）。
        """
        ctx = _ToolCtx(
            self.workspace_root,
            self.cancel_event,
            tool_call_id=tool_call_id,
            cwd=self.workspace_root,
            run_id=run.run_id,
            process_runner=self.process_runner,
            artifact_store=self.artifact_store,
        )
        deadline = tool.spec.timeout_s or run.budget.tool_default_timeout_seconds
        try:
            result = await asyncio.wait_for(tool.execute(args, ctx), timeout=deadline)
        except TimeoutError:
            result = ToolResult(
                status="timed_out",
                result=f"tool '{name}' exceeded its {deadline}s deadline set by the Harness",
                display=f"{name} timed out after {deadline}s",
            )
        except Exception as exc:  # noqa: BLE001 - 插件故障不得击穿内核（C10）
            # 只捕 Exception：CancelledError / KeyboardInterrupt / SystemExit 是 BaseException，
            # 取消与进程级中断必须继续向上传递，不能被"吃成"一个工具 error。
            result = ToolResult(
                status="error",
                result=f"tool '{name}' raised {type(exc).__name__}: {exc}",
                display=f"{name} crashed",
            )
        run, events = reduce(run, RecordToolResult(run_id=run.run_id, tool_call_id=tool_call_id, status=result.status, result=result.result, display=result.display))
        controller.run = run
        await self._emit(events)
        await self._checkpoint(run, "post_tool")  # 工具结果已落库 → 快照收窄在途窗口（ADR-0020）
        return run

    async def _apply_command(self, controller: RunController, run: Run, command: object) -> Run:
        """内部 helper：所有 lifecycle transition 都先落 authority，再 emit。"""
        run, events = reduce(run, command)  # type: ignore[arg-type]
        controller.run = run
        await self._emit(events)
        return run

    async def _handle_ask(self, controller: RunController, run: Run, tool: Tool, intent: ProposeToolCall, outcome: object) -> Run:
        """ask → durable approval request → inbox/timeout；绝不阻塞回调。"""
        target = next(c for c in run.tool_ledger.calls if c.tool_call_id == intent.tool_call_id)
        request_id = new_id("apr")
        timeout = run.budget.approval_timeout_seconds
        expires_at = utc_now() + timedelta(seconds=timeout)
        args_summary = getattr(outcome, "args_summary", target.name)
        reason = getattr(outcome, "reason", "approval required")
        run = await self._apply_command(
            controller,
            run,
            RequestApproval(
                run_id=run.run_id,
                tool_call_id=intent.tool_call_id or "",
                request_id=request_id,
                args_summary=args_summary,
                risk=target.risk or tool.spec.risk.value,
                reason=reason,
                expires_at=expires_at,
            ),
        )
        await self._checkpoint(run, "pre_tool")  # 审批挂起是可跨重启续跑的稳态 → durable（ADR-0020/0021）
        deadline = time.monotonic() + timeout
        while True:
            def relevant(command: object) -> bool:
                return isinstance(command, Cancel) or (
                    isinstance(command, ResolveApproval | ExpireApproval) and command.request_id == request_id
                )

            command = await controller.wait_for(relevant, timeout=max(0.001, deadline - time.monotonic()))
            if command is None:
                return await self._apply_command(controller, run, ExpireApproval(run_id=run.run_id, request_id=request_id))
            if isinstance(command, Cancel):
                return await self._apply_command(controller, run, command)
            run = await self._apply_command(controller, run, command)
            call = next(c for c in run.tool_ledger.calls if c.tool_call_id == (intent.tool_call_id or ""))
            if call.status is ToolCallStatus.READY:
                return await self._apply_command(
                    controller,
                    run,
                    MarkToolRunning(
                        run_id=run.run_id,
                        tool_call_id=intent.tool_call_id or "",
                        capability=tool.spec.capability.value,
                        risk=tool.spec.risk.value,
                        timeout_s=tool.spec.timeout_s or run.budget.tool_default_timeout_seconds,
                    ),
                )
            if call.status in {ToolCallStatus.DENIED, ToolCallStatus.CANCELLED}:
                return run

    async def _resume_settle_open_calls(self, controller: RunController, run: Run) -> Run:
        """把快照里仍 OPEN 的工具调用补齐再继续（ADR-0021）。

        - ``awaiting_approval``：等已存在的 request 被 Resolve/Expire/Cancel（不新建 request、不自动放行）。
        - ``ready``/``running``：已批准或曾在跑 → 直接补执行一次（at-least-once；真 exactly-once 靠 P9 claim）。
        - ``pending``/``validated``：崩溃在权限判定前 → **重走 ``_handle_tool_call``（含权限）**，
          绝不绕过 ask（否则 resume 会把未批的危险写静默放行）。
        完成后所有原 OPEN 调用都已闭合，再进入 provider-first 循环，配对得以保持。
        """
        for target_id in [c.tool_call_id for c in run.tool_ledger.calls if c.status in OPEN_TOOL_CALL_STATUSES]:
            if run.status.is_terminal or self.cancel_event.is_set():
                return run
            call = next((c for c in run.tool_ledger.calls if c.tool_call_id == target_id), None)
            if call is None or call.status not in OPEN_TOOL_CALL_STATUSES:
                continue
            if call.status is ToolCallStatus.AWAITING_APPROVAL:
                run = await self._resume_wait_for_approval(controller, run, call)
                call = next((c for c in run.tool_ledger.calls if c.tool_call_id == target_id), None)
                if call is None:
                    continue
            if call.status in {ToolCallStatus.READY, ToolCallStatus.RUNNING}:
                run = await self._resume_execute_call(controller, run, call)
            elif call.status in {ToolCallStatus.PENDING, ToolCallStatus.VALIDATED}:
                run = await self._handle_tool_call(controller, run, ProposeToolCall(name=call.name, args=dict(call.args), tool_call_id=target_id))
        return run

    async def _resume_wait_for_approval(self, controller: RunController, run: Run, call) -> Run:
        """恢复挂起的审批：等已存在 request 的 Resolve/Expire/Cancel，不新建 request（ADR-0021）。"""
        request_id = call.approval_request_id
        approval = next((a for a in run.permission_ctx.approvals if a.request_id == request_id), None)
        if approval is None or approval.expires_at <= utc_now():
            # request 丢失或已过期：fail-closed 经 reduce 闭合，绝不静默放行。
            return await self._apply_command(controller, run, ExpireApproval(run_id=run.run_id, request_id=request_id or ""))

        def relevant(command: object) -> bool:
            return isinstance(command, Cancel) or (
                isinstance(command, ResolveApproval | ExpireApproval) and command.request_id == request_id
            )

        remaining = (approval.expires_at - utc_now()).total_seconds()
        command = await controller.wait_for(relevant, timeout=max(0.001, remaining))
        if command is None:
            return await self._apply_command(controller, run, ExpireApproval(run_id=run.run_id, request_id=request_id))
        return await self._apply_command(controller, run, command)

    async def _resume_execute_call(self, controller: RunController, run: Run, call) -> Run:
        """补执行一个已批准（ready）或曾在跑（running）的调用；仅在未 running 时补 MarkToolRunning。"""
        tool = self._tool(call.name)
        if tool is None:
            run, events = reduce(run, RecordToolResult(run_id=run.run_id, tool_call_id=call.tool_call_id, status="error", result=f"unknown tool '{call.name}' on resume"))
            controller.run = run
            await self._emit(events)
            return run
        if call.status is not ToolCallStatus.RUNNING:
            run = await self._apply_command(
                controller,
                run,
                MarkToolRunning(
                    run_id=run.run_id,
                    tool_call_id=call.tool_call_id,
                    capability=tool.spec.capability.value,
                    risk=tool.spec.risk.value,
                    timeout_s=tool.spec.timeout_s or run.budget.tool_default_timeout_seconds,
                ),
            )
        return await self._execute_tool(controller, run, tool, call.tool_call_id, dict(call.args), call.name)

    async def _emit(self, events: list[Envelope]) -> None:
        """把一批事件逐条交给总线（可持久的会落库、live-only 只转发）。"""
        for env in events:
            await self.bus.emit(env)

    async def _live(self, run: Run, turn: int, etype: str, data: dict) -> None:
        # live-only delta：只转发给订阅者，永不持久化（design/01 I3）。
        await self.bus.emit(Envelope(v=1, seq=run.seq, run_id=run.run_id, type=etype, turn=turn, data=data))


def _has_text(message: Message) -> bool:
    """消息是否含非空可见文本块。"""
    return any(b.type == "text" and b.text for b in message.content)


def _token_total(usage: JsonObject) -> int:
    """从用量里取总 token（优先 total，回退 completion/output）；无则 0。"""
    for key in ("total_tokens", "completion_tokens", "output_tokens"):
        value = usage.get(key)
        if value:
            try:
                return int(value)
            except (TypeError, ValueError):
                return 0
    return 0


def _parse_args(raw: str) -> JsonObject:
    """解析工具入参 JSON 片段；不可解析则当空（后续 schema 校验会兼为错）。"""
    import json

    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}


def _bounded_raw_args(raw: str) -> str:
    """保留有界原始参数；不保存可能含密钥的无界文本（ADR-0019）。"""
    return raw[:4096]


def _finish_tool_use(index: int, slot: dict) -> ContentBlock:
    """把 provider 分片定稿成 tool_use，同时区分 valid/invalid/missing args。"""
    raw = slot["args"]
    if not raw:
        return ContentBlock(
            type="tool_use",
            tool_use_id=slot["id"] or new_id("tc"),
            name=slot["name"],
            raw_input="",
            args_status=ToolArgsStatus.MISSING,
            args_error="provider sent no tool arguments",
        )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return ContentBlock(
            type="tool_use",
            tool_use_id=slot["id"] or new_id("tc"),
            name=slot["name"],
            raw_input=_bounded_raw_args(raw),
            args_status=ToolArgsStatus.INVALID,
            args_error=exc.msg,
        )
    if not isinstance(parsed, dict):
        return ContentBlock(
            type="tool_use",
            tool_use_id=slot["id"] or new_id("tc"),
            name=slot["name"],
            raw_input=_bounded_raw_args(raw),
            args_status=ToolArgsStatus.INVALID,
            args_error="tool arguments must be a JSON object",
        )
    return ContentBlock(
        type="tool_use",
        tool_use_id=slot["id"] or new_id("tc"),
        name=slot["name"],
        input=parsed,
        raw_input=_bounded_raw_args(raw),
        args_status=ToolArgsStatus.VALID,
    )


def _unknown_tool_message(name: str, specs, surface: object | None = None) -> str:  # noqa: ANN001
    """静态候选只提示，不扩工具面（03 §6；P2 T14）。"""
    candidates: tuple[str, ...] = ()
    if surface is not None and hasattr(surface, "candidates"):
        candidates = surface.candidates(name)  # type: ignore[attr-defined]
    else:
        names = [spec.name for spec in specs]
        candidates = tuple(n for n in names if name[:2] and (n.startswith(name[:2]) or name[:2] in n))[:3]
    if candidates:
        return f"unknown tool '{name}'; did you mean: {', '.join(candidates)}?"
    return f"unknown tool '{name}'"


def _schema_error(params: JsonObject, args: JsonObject) -> str | None:
    """用 JSON-Schema 校验入参（C8 第一层）；非法则返回可读错误。"""
    validator = Draft202012Validator(params)
    errs = sorted(validator.iter_errors(args), key=lambda e: e.path)
    if not errs:
        return None
    return "invalid arguments: " + "; ".join(e.message for e in errs[:3])
