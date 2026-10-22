"""L2 turn 循环（design/04；HARD C7/C8/C10/C19）。P1 = 单模型、串行工具。

``DefaultTurnLoop`` 把一次 Run 驱动到唯一终态。它是*纯机制*：从不 import 具体
策略/工具/传输面——那些以 ``contracts`` 的 Port/回调注入（C1/C14）。所有状态变更经唯一
咽喉 ``state.transition.apply()``（幂等判定 → reduce 单写者）；delta 直发事件流、永不落库。

两条不许坏的接缝（ADR-0028）：
- **回发前配对关卡**：本模块是全仓唯一 ``ProviderPort.stream`` 调用点，关卡就长在这个调用点
  里——串行执行工具不变，但一条 assistant 里所有未答 tool_use 必须先闭合才允许下一次请求。
- **provider 故障边界**：外部错误归一 ``run_failed``（带 kind/retryable），绝不穿出 loop。

恪守的 phase 范围（ROADMAP §2.5）：仅串行工具（``parallel_safe`` 只是 schema 占位）、
单模型；取消/deny/非法意图/provider 故障四条路径均不得崩宿主进程。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from contextlib import ExitStack
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from jsonschema import Draft202012Validator

from questor.contracts.artifacts import OutputBudget
from questor.contracts.common import JsonObject, new_id, thaw, utc_now
from questor.contracts.errors import ErrorEntry, ErrorKind, ErrorLayer, RecoveryHints, classify_provider_error
from questor.contracts.events import (
    AdvanceTurn,
    AppendAssistantMessage,
    Cancel,
    Command,
    CompactContext,
    DeleteMemory,
    Envelope,
    EventType,
    ExpireApproval,
    FinalizeRun,
    MarkToolDenied,
    MarkToolRunning,
    MarkToolValidated,
    RecordToolResult,
    RecordTurnCompleted,
    RecordWarning,
    RequestApproval,
    ResolveApproval,
    SpawnSubagent,
    SubmitMessage,
    WarnCompaction,
    WriteMemory,
)
from questor.contracts.extension import (
    ExtensionDescriptor,
    ExtensionKind,
    HookOutcome,
    HookOutcomeKind,
    InterceptionPoint,
    ObserveChain,
    ObserveEntry,
)
from questor.contracts.memory import (
    CITATION_OPEN,
    MemoryCitation,
    MemoryScope,
    MemoryStorePort,
    MemoryWrite,
    MemoryWriteKind,
    RecallPort,
    consumption_kind_for,
    parse_citation,
    recall_skipped_by_flags,
)
from questor.contracts.policy import CompactionConfig, PolicyPort, PolicyView, ProposeToolCall, SuggestFinish
from questor.contracts.ports import ProviderPort, ProviderRequest, SandboxPort, StorePort, SummarizerPort
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
from questor.contracts.subagent import SpawnRequest, SpawnResult, SubagentSpawnerPort
from questor.contracts.submissions import command_digest
from questor.contracts.tool import RunToolSurface, Tool, ToolResult, ToolSpec
from questor.kernel.command_window import window_payload
from questor.kernel.compaction import (
    MAX_CONSECUTIVE_COMPACT_FAILURES,
    SUMMARY_MAX_CHARS,
    EvictWindow,
    evict_window,
    plan_compaction,
)
from questor.kernel.events import EventBus
from questor.kernel.permission_policy import PermissionDecision, PermissionEvaluation
from questor.kernel.run_control import RunController
from questor.kernel.settle import TurnBoundary
from questor.kernel.shell_parse_posix import parse_posix_shell
from questor.kernel.shell_parse_powershell import parse_powershell
from questor.kernel.tool_arguments import extract_shell_commands
from questor.memory.cache_plan import CachePlan, CacheSegments, break_reason, cache_ttl_for, plan_cache
from questor.observability.redact import strip_prompt_echo
from questor.observability.scope import bind
from questor.state.checkpoint import open_tool_use_ids
from questor.state.domain_state import Run
from questor.state.snapshot import to_snapshot
from questor.state.transition import Applied, apply


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
        memory_store: MemoryStorePort | None = None,
        subagent_spawner: SubagentSpawnerPort | None = None,
    ) -> None:
        self.workspace_root = workspace_root
        self.cwd = cwd or workspace_root
        self.tool_call_id = tool_call_id
        self.run_id = run_id
        self._process_runner = process_runner
        self._artifact_store = artifact_store
        self._memory_store = memory_store
        self._subagent_spawner = subagent_spawner
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

    async def memory_search(self, query: str, *, k: int = 8, scope: object | None = None) -> tuple:
        """经 Harness 持有的 MemoryStorePort 取**有界**检索命中；工具拿不到裸句柄（C4）。

        无 store（未装配记忆）时返回空、不抛——降级为"无记忆可用"，不破循环。"""
        if self._memory_store is None:
            return ()
        return await self._memory_store.search(query, k=k, scope=scope)

    async def spawn_subagent(
        self,
        objective: str,
        *,
        requested_mode: str | None = None,
        extra_deny: tuple[str, ...] = (),
        wait: bool = True,
    ) -> SpawnResult:
        """经 Harness 注入的 spawner 端口发起一个子 agent（独立 Run，ADR-0038）。

        工具拿不到 RunRegistry/bus 裸句柄（C4/C8）；spawn 的记账/建子/起跑全在端口与内核。
        未接线（单 run 场景）时 fail-soft 返回未受理、不抛——不破坏既有循环。``wait=False`` 为
        fire-and-forget（不起回、父继续），使多个 live 子可同时存在、宽度门才真实可达。
        """
        if self._subagent_spawner is None:
            return SpawnResult(accepted=False, reason="subagent orchestration not wired")
        return await self._subagent_spawner.delegate(
            _spawn_request_from(self.run_id, objective, requested_mode, extra_deny, wait)
        )


def _spawn_request_from(
    parent_run_id: str,
    objective: str,
    requested_mode: str | None,
    extra_deny: tuple[str, ...],
    wait: bool = True,
) -> SpawnRequest:
    """把工具的委派意图包成端口请求。node_id 在此先起一个稳定 id，端口侧用它建节点与绑定子 run。"""
    return SpawnRequest(
        parent_run_id=parent_run_id,
        node_id=new_id("node"),
        objective=objective,
        requested_mode=requested_mode,
        extra_deny=tuple(extra_deny),
        wait=wait,
    )


def _none_descriptor() -> SandboxDescriptor:
    return SandboxDescriptor(
        backend=SandboxBackend.NONE,
        confinement=Confinement.NONE,
        fences_writes=False,
        fences_network=False,
        isolates_process_tree=False,
        limitation="no sandbox backend available",
    )


# 内核一方 inline 记录 logger（走 observability 桥进主干；策略/故障留痕用，#171）。
_log = logging.getLogger("questor.loop")


def _analyze_shell(tool_spec: ToolSpec, arguments: JsonObject) -> ShellAnalysis | None:
    """只按 ToolSpec capability/name 选 dialect；不靠工具名字符串猜安全。"""
    commands = extract_shell_commands(arguments)
    if not commands:
        return None
    powershell = tool_spec.name.lower() in {"powershell", "pwsh"}
    analyses = [parse_powershell(command) if powershell else parse_posix_shell(command) for command in commands]
    if any(analysis.status is not ShellParseStatus.PARSED for analysis in analyses):
        # 任一子命令未解析/动态/不支持 → 整体不可证明只读：返回**首个非 PARSED** 分析（all_read_only=False），
        # 交 EXEC 能力下限 fail-closed 判；绝不用 analyses[0]（可能是已解析只读）造成 exec fail-open（#169）。
        return next(analysis for analysis in analyses if analysis.status is not ShellParseStatus.PARSED)
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


def _submit_key(command: SubmitMessage, run: Run) -> str:
    """用户消息的**内容派生**幂等键（B1/c3）：``submit:<turn>:<content_sha256>``。

    为何不能沿用通用键：通用键只含 ``command.type`` 与游标，同一安全点批量消费的两条不同用户消息
    会撞成同键 → ``apply`` 判成“同 key 异 digest”拒绝（``IdempotencyConflictError``）或误判为重复。
    内容派生键使：同内容重投 → 同键 → no-op（不重复追加）；不同内容 → 不同键 → 各自进事实流。
    """
    text = "".join(b.text or "" for b in command.content.content if b.type == "text")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"submit:{run.turn}:{digest}"


def _transition_key(command: Command, run: Run) -> str:
    """幂等键：命令类型 + 当前游标 + 关联键（同状态上同一命令 → 同键；不同命令 → 不同键）。

    不含随机量：重投/重放的同一命令在同一状态上得到同一键，``apply`` 才能识别“已应用”；
    不同命令即使同类型也因关联键/状态游标不同而自动分开（不会误判成冲突）。

    ``SubmitMessage`` 例外走内容派生键（B1/c3，见 :func:`_submit_key`）：用户消息的“同一意图”
    由正文决定，不由游标决定。
    """
    if isinstance(command, SubmitMessage):
        return _submit_key(command, run)
    tied = (
        getattr(command, "tool_call_id", "")
        or getattr(command, "request_id", "")
        or getattr(command, "node_id", "")
        or ""
    )
    status = getattr(command, "status", "") or ""
    return f"{command.type}:{run.seq}:{run.turn}:{tied}:{status}"


def _settle_chain_from_callback(settle: Callable[[TurnBoundary], Awaitable[None]] | None) -> ObserveChain:
    """R3 兼容：把旧 ``settle=`` callable 包成**单条** Stop OBSERVE 条目。

    这是为了让既有 ``DefaultTurnLoop(settle=...)`` 调用点零改动；内核只持 ``_stop`` 一个字段，
    ``_settle_turn`` 只有一个调用点——不是两套机制并存（ADR-0053）。
    """
    if settle is None:
        return ObserveChain()

    async def _hook(payload: object) -> HookOutcome:
        await settle(payload)  # type: ignore[arg-type]
        return HookOutcome()

    descriptor = ExtensionDescriptor(
        id="settle-turn",
        kind=ExtensionKind.OBSERVE,
        at=InterceptionPoint.STOP.value,
        priority=100,
    )
    return ObserveChain((ObserveEntry(descriptor, _hook),))


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
        memory_store: MemoryStorePort | None = None,
        workspace_root: Path | None = None,
        model: str = "",
        system: str | None = None,
        cancel_event: asyncio.Event | None = None,
        subagent_spawner: SubagentSpawnerPort | None = None,
        capability_probe: Callable[[], int] | None = None,
        compaction: CompactionConfig | None = None,
        settle: Callable[[TurnBoundary], Awaitable[None]] | None = None,
        stop: ObserveChain | None = None,
        memory_injection: JsonObject | None = None,
        query_source: str = "main",
        recall: RecallPort | None = None,
        memory_root: Path | None = None,
        summarizer: SummarizerPort | None = None,
        output_envelope: object | None = None,
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
        self.memory_store = memory_store
        self.workspace_root = workspace_root or Path.cwd()
        self.model = model
        self.system = system
        self.cancel_event = cancel_event or asyncio.Event()
        # P8：子 agent 编排端口（未接线时单 run 行为逐字不变）。spawn 建子与子树冻结均走此端口。
        self.subagent_spawner = subagent_spawner
        # P10/ADR-0048：可恢复压缩旋钮；None = 不压缩（向后兼容，等价旧 disable_compaction=True）。
        self.compaction = compaction
        # B10/§7.3–7.4：可注入摘要器（未给则用 L2 确定性启发式）；熔断只数**连续**失败，
        # 预警按窗口去重（一个窗口一次“快满了”，不静默也不刷屏）。两者都是 run 内状态。
        self.summarizer = summarizer
        self._compact_failures = 0
        self._warned_windows: set[int] = set()
        self._usage_source = "estimated"
        # §7.2 C-1（BLK-10 收口）：大工具输出归档的信封工厂，由 **surface 注入**（形状取
        # `capabilities.tools._output.envelope_for_text`）——kernel 不 import L3，所以递的是 callable。
        # 未注入（直接拼 loop 的旧路径）则工具结果逐字不变，既有行为不破。
        self.output_envelope = output_envelope
        # B6/B5：Stop 点是 settle 的唯一入口。``stop`` 是装配好的 OBSERVE 链；
        # ``settle=`` 是 R3 兼容薄糖（既有测试直接传 callable），内部包成单条 Stop 链，
        # **不存在第二套回调字段**。
        self._stop = stop if stop is not None else _settle_chain_from_callback(settle)
        # B7（§6.1 第④约束）：已装进 system 定界子段的索引段计量。loop **不读正文**，
        # 只在首次真正发出请求时落一条 live-only `memory_injected`（“请求里确实带了它”才可归因）。
        self.memory_injection = memory_injection
        self._memory_injection_announced = False
        # B7（§6.1 cache 三条款）：TTL 按 query source 门控——side-query（终选器/摘要器）
        # 不开 cache，也就不得把用户前缀的断裂事件规到自己头上（避免面板/日志被内部调用污染）。
        self.query_source = query_source
        self._cache_ttl = cache_ttl_for(query_source)
        self._cache_plan: CachePlan | None = None
        # B8（§6.2/§6.3）：召回只经注入的 RecallPort（kernel 不 import memory 层）；
        # ``memory_root`` 只用来判定“这次 Read 读的是不是记忆文件”（花费打点用）。
        self.recall = recall
        self.memory_root = memory_root
        # 门控③：上一轮消费到的 ``skip_recall`` 标记只对**下一次发请求**生效（一次性）。
        self._recall_skip = False
        self._recalled_ids: set[str] = set()
        # B8（§6.3）：本轮从正文剥出的引用，由 `_drive_controller` 随 AppendAssistantMessage 一次携带。
        # 存局部变量而不是改返回 arity：`_stream_turn` 的三元组已被既有测试钉住（R3 不改断言）。
        self._turn_citations: MemoryCitation | None = None
        # P9/ADR-0046：能力名册探针（未注入则不发 tools_changed）。loop 每安全点比对、变化即发 live-only。
        self.capability_probe = capability_probe
        self._capability_gen = capability_probe() if capability_probe is not None else 0

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
            # 终态也落一个权威快照（completed/failed/cancelled）：否则对已结束的 run 重建
            # 会拿到 turn 边界那个 status=running 的 stale 快照，resume 会重驱一轮（真实 LLM 冒烟发现）。
            if result.status.is_terminal and self.store is not None:
                await self._checkpoint(result, "final")
            if result.status.is_terminal and self.subagent_spawner is not None:
                # P8（ADR-0038/C7）：父 terminal → 冻结子树——经端口向每个 live 子提 Cancel(owner)，
                # 不 out-of-band 硬杀；无子时端口自会 no-op。
                await self.subagent_spawner.on_parent_terminal(result.run_id)
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
        # 保留这个入口点而不只依赖循环内关卡：它在 ``turn += 1`` 之前，所以被 kill 的 run
        # 不会为了补一个已批准的工具而多花一轮预算（ADR-0021 测过的行为，ADR-0028 不改）。
        run = await self._settle_open_calls(controller, run)
        turn = run.turn
        started = time.monotonic()
        total_tokens = 0
        faults = 0
        repeat_sig: tuple | None = None
        repeat_count = 0
        empties = 0
        turn_assistant: Message | None = None
        # 关联作用域（α′，DESIGN §5；G-L5）：run_id 整轮一次绑定（覆盖新鲜+resume 两条路），
        # turn 每轮从 loop 权威局部变量 ``turn`` 重盖章（同名覆盖→号不漂移）。ExitStack 退出时
        # 统一 reset，绝不把本 run 的关联泄漏进调用方 task（http_sse 并发多 run 靠 task 作用域隔离）。
        with ExitStack() as stack:
            stack.enter_context(bind(run_id=run.run_id))
            while True:
                run = await self._consume_commands(controller, run)
                if run.status.is_terminal:
                    return run
                if self.cancel_event.is_set():
                    if turn_assistant is not None:
                        run = await self._apply_command(
                            controller,
                            run,
                            RecordTurnCompleted(run_id=run.run_id, turn=turn, usage={}, interrupted=True),
                        )
                        await self._settle_turn(run, turn, turn_assistant, {}, interrupted=True)
                    run, events = await self._transition(run, Cancel(run_id=run.run_id, reason=CancelReason.USER))
                    controller.run = run
                    await self._emit(events)
                    return run
                if run.budget.deadline_seconds is not None and (time.monotonic() - started) > run.budget.deadline_seconds:
                    return await self._fail(run, turn, ErrorKind.TIMEOUT, f"wall-clock deadline {run.budget.deadline_seconds}s exceeded", "deadline")

                # P9 安全点：能力名册变了→发 live-only tools_changed（活 run 面不变，仅告知外部观察者）。
                await self._maybe_announce_capability(run, turn)

                turn += 1
                stack.enter_context(bind(turn=turn))  # 每轮重盖章：inline 行据此携当前 turn（G-L5 判红点）
                if turn > run.budget.max_turns:
                    return await self._fail(run, turn, ErrorKind.TIMEOUT, f"max_turns {run.budget.max_turns} exhausted", "budget_exhausted")

                turn_start = run  # C10/X4 回滚点：本 turn 起始时的状态
                run, events = await self._transition(run, AdvanceTurn(run_id=run.run_id, turn=turn))
                controller.run = run
                await self._emit(events)

                run, assistant_msg, usage = await self._stream_turn(controller, run, turn)
                if assistant_msg is None:
                    # 本轮没向 provider 发出请求，或请求已失败并归一：run 已终态就直接交回；
                    # 非终态只可能是关卡期间被取消——回循环顶走 Cancel→reduce（C7），
                    # 绝不在这条支路里造第二套终止路径（C13 恰一终态）。
                    if run.status.is_terminal:
                        return run
                    continue
                total_tokens += _token_total(usage)
                if usage:
                    # §7.1 信号源：模型报回来的 usage 是 **server-observed**，比任何本地估算都可信；
                    # 没报（假 provider / 只产文本）就仍是 estimated，摘要与阈值都按它标来源，不冒充观测值。
                    self._usage_source = "server_observed"
                citations, self._turn_citations = self._turn_citations, None
                run, events = await self._transition(
                    run, AppendAssistantMessage(run_id=run.run_id, turn=turn, message=assistant_msg, citations=citations)
                )
                controller.run = run
                await self._emit(events)
                if not any(env.type == EventType.MESSAGE_COMPLETED for env in events):
                    # reduce **拒收**了这条 assistant（重复 tool_use_id）：Domain_State 没长。此时必须
                    # 出声——不能继续把本地 ``assistant_msg`` 当已落库的定稿：实测它会被后面的
                    # ``FinalizeRun(final=…)`` 原样写回 context，留下一条永远没有 tool_result 的悬空
                    # tool_use，且因终态而不进 ``--list``/resume（ADR-0028，比崩更难查）。
                    entry = ErrorEntry(
                        kind=ErrorKind.FORMAT_ERROR,
                        layer=ErrorLayer.PROVIDER,
                        message="assistant message rejected by state: duplicate tool_use id in provider answer",
                        at_turn=turn,
                        hints=RecoveryHints(),
                        cause="AppendAssistantMessageRejected",
                        timestamp=utc_now(),
                    )
                    return await self._fail_with_entry(run, turn, entry, "provider_protocol_error")
                await self._checkpoint(run, "auto")
                turn_assistant = assistant_msg

                # P10/ADR-0048：turn 边界安全点（快照已落、全部 tool_use 已闭合）尝试可恢复压缩。
                # I2：压缩由内核决定（策略只能发 advisory hint）；未配 compaction 则逐字不变。
                await self._maybe_warn_pressure(controller, run, turn, total_tokens)
                run = await self._maybe_compact(controller, run, turn, total_tokens)
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
                    # durable 告警必须经 reduce 取号（否则复用已占 seq 撞 UNIQUE，track5-backbone BLK-1 path A）。
                    run, wev = await self._transition(run, RecordWarning(run_id=run.run_id, turn=turn, message="policy raised; rolling back turn (C10)"))
                    await self._emit(wev)
                    # 回滚 Domain_State 到 turn 起点，但**保住单调 seq 游标**（已落库的事件号不得重用）。
                    run = replace(turn_start, seq=run.seq)
                    if faults > 2:
                        return await self._fail(run, turn, ErrorKind.POLICY_VIOLATION, "policy raised repeatedly", "policy_error")
                    continue
                faults = 0

                if isinstance(intent, SuggestFinish):
                    if any(c.status in OPEN_TOOL_CALL_STATUSES for c in run.tool_ledger.calls):
                        continue  # stop-gate：尚有未闭合工具调用时拒绝过早 Finish
                    # W5-002：finish 前排空 inbox——provider 阻塞期间到达的 Cancel 必须经 reduce 把 run
                    # 迁到 cancelled，绝不把用户已请求取消的 run 谎报为 completed。
                    run = await self._consume_commands(controller, run)
                    if run.status.is_terminal:
                        return run
                    final = assistant_msg if has_text else None
                    # B6 Stop 点：先落 durable turn_completed + settle，再收终态（顺序固定，便于回放）。
                    run = await self._apply_command(
                        controller,
                        run,
                        RecordTurnCompleted(run_id=run.run_id, turn=turn, usage=usage, interrupted=False),
                    )
                    await self._settle_turn(run, turn, final, usage, interrupted=False)
                    run, events = await self._transition(run, FinalizeRun(run_id=run.run_id, status="completed", final=final, usage=usage, exit_reason="answered"))
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
        """按 FIFO 应用 inbox 中已到达的 Command；迁移一律经 ``apply`` 单入口。"""
        applied: list[Command] = []
        batch = await controller.next_batch()
        try:
            for command in batch:
                run, events = await self._transition(run, command, source="inbox")
                applied.append(command)
                controller.run = run
                await self._emit(events)
                # 记忆写副作用：reduce 已受理（产 memory_written）后，由 kernel 在消费点经注入的
                # MemoryStorePort 落库——写唯一入口仍是 Command（C4/C16），幂等键取已占的 durable seq。
                if isinstance(command, SubmitMessage) and recall_skipped_by_flags(command.flags):  # type: ignore[arg-type]
                    # 门控③：系统/自动轮次（提交方显式标了 skip_recall）下一轮不召回。
                    self._recall_skip = True
                if isinstance(command, WriteMemory) and self.memory_store is not None:
                    ack = next((env for env in events if env.type == EventType.MEMORY_WRITTEN), None)
                    if ack is not None:
                        await self.memory_store.write(command.payload, idempotency_key=f"mem:{command.run_id}:{ack.seq}")
                if isinstance(command, DeleteMemory) and self.memory_store is not None:
                    # B9 纪律⑥：事件已受理才做软删（与写同纪律：reduce 发事、消费点做 IO）。
                    ack = next((env for env in events if env.type == EventType.MEMORY_DELETED), None)
                    if ack is not None:
                        soft_delete = getattr(self.memory_store, "soft_delete", None)
                        if callable(soft_delete):  # 旧/简 store 无此能力时跳过（additive 端口方法）
                            await soft_delete(command.entry_id, idempotency_key=f"memdel:{command.run_id}:{ack.seq}")
                # P8（ADR-0038/§4.1）：reduce 受理 SpawnSubagent（产出 peer_started = 已绑 node）后，
                # 才由端口实体化子 run——对齐 WriteMemory 的"reduce 发事件、消费点做 IO"。reduce 若判重/拒
                # （无 peer_started）则不建子，避免重投/回放留下孤儿子。
                if isinstance(command, SpawnSubagent) and self.subagent_spawner is not None:
                    if any(e.type == EventType.PEER_STARTED for e in events):
                        await self.subagent_spawner.materialize_child(command.run_id, command.node_id, command.child_run_id)
                if run.status.is_terminal:
                    return run
            return run
        finally:
            # 耐久队列：只 ack 已成功应用的命令；异常/早退时未应用的行保持 deferred，重启可重取。
            await controller.ack(tuple(applied))

    async def _settle_turn(
        self,
        run: Run,
        turn: int,
        assistant_msg: Message | None,
        usage: JsonObject,
        *,
        interrupted: bool,
    ) -> None:
        """Stop/Interrupt 点：把边界事实交给 Stop 点位的观察链；失败绝不打断回复。"""
        if not self._stop:
            return
        boundary = TurnBoundary(
            run_id=run.run_id,
            turn=turn,
            user_text=_last_real_user_text(run),
            assistant_text=_visible_text(assistant_msg),
            interrupted=interrupted,
            usage=dict(usage or {}),
        )
        outcomes = await self._stop.emit(boundary)
        for outcome in outcomes:
            if outcome.kind is not HookOutcomeKind.SUCCESS:
                _log.warning(
                    "stop hook %s ended %s: %s",
                    outcome.entry_id,
                    outcome.kind.value,
                    outcome.reason,
                )

    async def _window_identity(self, run: Run) -> JsonObject:
        """从 **现有 `command_window` 行** 派生本 run 的压缩窗口身份（B10/§7.1，零新表）。

        store 不支持时返回单窗口默认（number=0、身份 None），压缩照旧工作、只是事件不带身份。"""
        window_identity = getattr(self.store, "window_identity", None)
        if not callable(window_identity):
            return {"window_number": 0, "window_id": None, "previous_window_id": None}
        try:
            row = await window_identity(run.run_id)
        except Exception:  # noqa: BLE001 - 身份是观测面，拿不到就降级为无身份，绝不拖垮压缩
            _log.warning("window identity lookup failed run=%s", run.run_id, exc_info=True)
            return {"window_number": 0, "window_id": None, "previous_window_id": None}
        if not row:
            return {"window_number": 0, "window_id": None, "previous_window_id": None}
        return {
            "window_number": int(row.get("window_number", 0)),
            "window_id": row.get("window_id"),
            "previous_window_id": row.get("previous_window_id"),
        }

    async def _emit_compact_warning(
        self,
        controller: RunController,
        run: Run,
        turn: int,
        *,
        reason: str,
        trigger: str,
        used_tokens: int | None,
        threshold: int | None,
        window_number: int,
        failures: int,
    ) -> Run:
        """落一条 durable `compact_warning`（同 `RecordWarning`：经 reduce 取号，保 seq 单调）。"""
        run, events = await self._transition(
            run,
            WarnCompaction(
                run_id=run.run_id,
                turn=turn,
                reason=reason,
                trigger=trigger,
                used_tokens=used_tokens,
                threshold=threshold,
                window_number=window_number,
                failures=failures,
            ),
        )
        controller.run = run
        await self._emit(events)
        return run

    async def _maybe_warn_pressure(self, controller: RunController, run: Run, turn: int, total_tokens: int) -> None:
        """§7.1 预警：累计用量越过 `EW - warning_buffer` 就发一次“快满了”（每个窗口只发一次）。

        未配 `context_window`（算不出绝对阈值）时完全不动作，行为逐字同 P10。"""
        if self.compaction is None:
            return
        threshold = self.compaction.warning_threshold()
        if threshold is None or total_tokens < threshold:
            return
        identity = await self._window_identity(run)
        number = int(identity["window_number"])
        if number in self._warned_windows:
            return  # 一次窗口一次告警：不静默，也不刷屏
        self._warned_windows.add(number)
        await self._emit_compact_warning(
            controller,
            run,
            turn,
            reason="pressure",
            trigger="auto",
            used_tokens=total_tokens,
            threshold=threshold,
            window_number=number,
            failures=self._compact_failures,
        )

    async def _summary_for(self, window: EvictWindow) -> str | None:
        """有 `SummarizerPort` 就问它（异步 IO 不得进 L2 纯决策），否则返回 None 用内置启发式。

        摘要器报错不冒泡：压缩失败是合法结果（熔断会计它），但绝不能把回复带崩。"""
        if self.summarizer is None:
            return None
        try:
            return await self.summarizer.summarize(window.evicted, max_chars=SUMMARY_MAX_CHARS)
        except Exception:  # noqa: BLE001 - 摘要器故障计入熔断，不击穿回复（C10 同向）
            _log.warning("summarizer raised; falling back to deterministic summary", exc_info=True)
            self._compact_failures += 1
            return None

    async def _maybe_compact(self, controller: RunController, run: Run, turn: int, total_tokens: int, *, trigger: str = "auto") -> Run:
        """P10/ADR-0048：在 turn 边界安全点尝试一次**可恢复压缩**。

        步骤（全部经 Command→reduce→durable，绝不上 out-of-band）：
        1. 纯决策 `plan_compaction`（无 IO）定当否压、逐出哪段、携带的 summary/锚；
        2. 先落 `pre_compact` 全量快照（design/01 §5）——压缩前态可确定性还原；
        3. 提交 `CompactContext` 命令→reduce 纯应用（携摘要/锚）→发 compact_started/applied；
        4. L2' 蒸馏桥（ADR-0025）：被压区浓缩经 `WriteMemory(kind=distill)` 写 daily（仅装配了
           memory_store 时），使“压缩不丢事实召回”可经检索回读。未配则 no-op（向后兼容）。
        """
        if self.compaction is None:
            return run
        if trigger == "auto" and self._compact_failures >= MAX_CONSECUTIVE_COMPACT_FAILURES:
            # §7.3 熔断：跳闸后**不再自动压**（没有它的代价写在 Claude-Code 注释里：1,279 个会话、
            # 最高 3,272 次连续失败）。溢出则走既有 budget/失败归一路径，不静默重试烧钱。
            return run
        window = evict_window(run, self.compaction, total_tokens, trigger=trigger)
        if window is None:
            return run
        summary_text = await self._summary_for(window)
        plan = plan_compaction(run, self.compaction, total_tokens, trigger=trigger, summary_text=summary_text)
        if plan is None:
            return run
        identity = await self._window_identity(run)
        await self._checkpoint(run, "pre_compact")  # 压缩前全量快照，保证可确定性还原压缩前态
        run, events = await self._transition(
            run,
            CompactContext(
                run_id=run.run_id,
                evict_start=plan.evict_start,
                evict_end=plan.evict_end,
                summary_text=plan.summary_text,
                new_floor=plan.new_floor,
                new_pointers=plan.new_pointers,
                trigger=plan.trigger,
                source=self._usage_source,
                window_id=identity["window_id"],
                previous_window_id=identity["previous_window_id"],
                window_number=int(identity["window_number"]),
                before_tokens=total_tokens,
                after_tokens=None,  # 逐出后的累计用量本轮未知：不编造（None 不进事件字段假数）
            ),
        )
        controller.run = run
        await self._emit(events)
        if not any(e.type == EventType.COMPACT_APPLIED for e in events):
            # reduce 拒了（如越 closed_prefix）→不进蒸馏写，并计入连续失败（§7.3 熔断）。
            self._compact_failures += 1
            if trigger == "auto" and self._compact_failures >= MAX_CONSECUTIVE_COMPACT_FAILURES:
                run = await self._emit_compact_warning(
                    controller,
                    run,
                    turn,
                    reason="breaker_tripped",
                    trigger="auto",
                    used_tokens=total_tokens,
                    threshold=self.compaction.auto_threshold(),
                    window_number=int(identity["window_number"]),
                    failures=self._compact_failures,
                )
            return run
        self._compact_failures = 0  # 一次成功就清零：熔断只数**连续**失败
        # L2' 蒸馏桥：被压区浓缩写 daily（正文只放浓缩、绝不放 delta/原文，I3）。
        if self.memory_store is not None:
            p = plan.new_pointers[0]
            payload = MemoryWrite(
                kind=MemoryWriteKind.DISTILL,
                scope=MemoryScope.SHARED,
                text=plan.summary_text,
                covered_from=p.seq_from,
                covered_to=p.seq_to,
                covered_hash=p.covered_hash,
            )
            run, mev = await self._transition(run, WriteMemory(run_id=run.run_id, payload=payload))
            controller.run = run
            await self._emit(mev)
            ack = next((e for e in mev if e.type == EventType.MEMORY_WRITTEN), None)
            if ack is not None:
                await self.memory_store.write(payload, idempotency_key=f"mem:{run.run_id}:{ack.seq}")
        # 压缩应用后立即落 post_compact 快照：否则崩在“压缩生效与下一轮 auto 快照”之间时，
        # rebuild 取到 seq 最大的 pre_compact（未压缩态）→ 压缩本想缓解的 provider 溢出复活
        # （track5-backbone MAJ-3）。checkpoints 按 seq DESC，post_compact 序号更大、优先命中；
        # pre_compact 仍保留供 verify_recovery_anchors 回读被逐区原文。
        await self._checkpoint(run, "post_compact")
        return run

    # ---- phase 辅助方法 ------------------------------------------------
    async def _stream_turn(self, controller: RunController, run: Run, turn: int) -> tuple[Run, Message | None, JsonObject]:
        """回发前唯一关卡 + provider 故障边界（ADR-0028；HARD C19）。

        顺序固定为“先配齐、后请求”：本方法是全仓唯一的 ``ProviderPort.stream`` 调用点，
        关卡写在调用点内部 = 任何路径（含 stop-gate、resume、未来第二个策略）都无法带着
        悬空 tool_call 回发。串行执行本身不变（不启用并行，ROADMAP §2.5）。

        返回 ``(run, assistant_msg, usage)``；``assistant_msg is None`` 表示本轮**未发出**请求
        （关卡已将 run 推到终态、期间被取消、或 provider 故障已归一 failed）。
        失败语义：本函数不向上抛 provider 异常（取消/KeyboardInterrupt 等 BaseException 除外）。
        """
        run = await self._ensure_paired_history(controller, run, turn)
        if run.status.is_terminal or self.cancel_event.is_set():
            return run, None, {}
        try:
            message, usage = await self._consume_stream(run, turn)
        except Exception as exc:  # noqa: BLE001 - provider 是外部故障域：归一成终态，不得打穿宿主进程（C10 对称面）
            # 只捕 Exception：CancelledError / KeyboardInterrupt / SystemExit 属 BaseException，
            # 取消与进程级中断必须继续传递，不能被“吃”成一个 run_failed（同 _execute_tool 纪律）。
            entry = classify_provider_error(exc, at_turn=turn)
            # provider 4xx 常把请求体（含本轮 prompt）整段回显：在**源头**剥回显，使 run_failed 事件、
            # 快照、主干日志三条下游都不落 prompt 明文（#162B；DESIGN §8 “主干零明文”）。
            if entry.message:
                entry = replace(entry, message=strip_prompt_echo(entry.message, _prompt_echo_baseline(run)))
            return await self._fail_with_entry(run, turn, entry, "provider_error"), None, {}
        message = await self._strip_citation(run, turn, message)
        return run, message, usage

    async def _ensure_paired_history(self, controller: RunController, run: Run, turn: int) -> Run:
        """把上一条 assistant 里**所有**未应答的 tool_use 闭合，否则不允许回发（I1/C7/C19）。

        为什么判据取 context 侧 ``open_tool_use_ids`` 而不是账本的 OPEN 集合：回填/重派只能处理
        “有 OPEN 条目”的调用，而实测存在“context 有悬空 tool_use、ledger 里根本没条目”的分裂态
        （ADR-0028）。以**真正要发出去的形状**为准才拦得住，provider 校验的就是这条规则。

        执行委托 ADR-0021 的 ``_settle_open_calls``（resume 入口与本题共用一套机制）：
        pending/validated 重走权限、awaiting_approval 等现有 request，绝不绕过 ask。
        不可调和（补执行后仍悬空）→ fail-closed 落 failed 并点名 id，**一次都不发**：
        宁可为一个带缺陷的历史报错终止，也不能靠合成 tool_result 骗过协议（ADR-0028 被否方案 B）。
        """
        if not open_tool_use_ids(run.context.items):
            return run
        run = await self._settle_open_calls(controller, run)
        if run.status.is_terminal or self.cancel_event.is_set():
            return run  # 取消/终态优先：剩下的悬空由 Cancel/FinalizeRun 的回填分支闭合（C7）
        still_open = open_tool_use_ids(run.context.items)
        if still_open:
            entry = ErrorEntry(
                kind=ErrorKind.FORMAT_ERROR,
                layer=ErrorLayer.KERNEL,
                message=f"unpaired tool_use in durable history cannot be settled before the next provider request: {list(still_open)}",
                at_turn=turn,
                hints=RecoveryHints(),
                cause="PairingGate",
                timestamp=utc_now(),
            )
            return await self._fail_with_entry(run, turn, entry, "pairing_violation")
        return run

    async def _consume_stream(self, run: Run, turn: int) -> tuple[Message, JsonObject]:
        """跑一轮流式：逐块 emit live delta、累积文本/工具参/用量，定稿为一条 assistant 消息。

        失败语义：不自己捕获异常——由 ``_stream_turn`` 的统一边界归一（免得分类漏在多处）。
        """
        # 压缩逐出的中段既不在 items、摘要若不回填则模型直接丢内容（track5-backbone MAJ-4）：
        # 有 summary 时作为首条 user 消息前缀注入，使“压缩不丢上下文”对模型可见（未配压缩时 summary 空、行为不变）。
        messages = run.context.items
        if run.context.summary:
            summary_msg = Message(
                id=f"summary:{run.run_id}",
                role=Role.USER,
                content=(ContentBlock(type="text", text=f"[之前对话的摘要]\n{run.context.summary}"),),
                seq=0,
            )
            messages = (summary_msg, *messages)
        # B8（§6.1 档2）：召回正文**绝不进 system**，只作 user-role 前缀消息进尾部易变段。
        recall_message = await self._build_recall_message(run, turn)
        if recall_message is not None:
            messages = (*messages, recall_message)
        await self._announce_memory_injection(run, turn)
        request = ProviderRequest(model=self.model, messages=messages, tools=self._specs(), system=self.system)
        await self._track_cache_break(run, turn, request)
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
        """以 failed 终态优雅收尾（归一化 ErrorEntry 入栈）。内核自身故障走这条（layer=KERNEL）。"""
        err = ErrorEntry(kind=kind, layer=ErrorLayer.KERNEL, message=message, at_turn=turn, hints=RecoveryHints(), timestamp=utc_now())
        return await self._fail_with_entry(run, turn, err, exit_reason)

    async def _fail_with_entry(self, run: Run, turn: int, err: ErrorEntry, exit_reason: str) -> Run:
        """用**已归一**的 ErrorEntry 落 failed 终态（provider/关卡故障按各自 layer/kind/hint 出声）。

        为什么另开一条：``_fail`` 把 layer 写死 KERNEL，会把 provider 故障误报成内核 bug；
        design/01 §8 要求 envelope 能定位子系统，ADR-0010 的 ``retryable``/``should_compress``
        也必须原样带到 ``run_failed``，否则客户端与 P10 的重试编排无从决策。
        配对：``FinalizeRun`` 分支自带未闭合调用回填，failed 路径同样不破 I1/C7。
        """
        run, events = await self._transition(run, FinalizeRun(run_id=run.run_id, status="failed", error=err, exit_reason=exit_reason))
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
        except Exception:  # noqa: BLE001 - 策略故障绝不得打断循环，但必须留痕供排障（#171）
            _log.warning("policy.propose_action raised; isolating turn", exc_info=True)
            return None, True

    async def _handle_tool_call(self, controller: RunController, run: Run, intent: ProposeToolCall) -> Run:
        """工具路由：args→schema→validated→permission→sandbox→execute。"""
        call = next((c for c in run.tool_ledger.calls if c.tool_call_id == intent.tool_call_id), None)
        if call is None:
            run, events = await self._transition(run, RecordToolResult(run_id=run.run_id, tool_call_id=intent.tool_call_id or "", status="error", result="missing tool_use ledger entry"))
            controller.run = run
            await self._emit(events)
            return run
        if call.args_status is not ToolArgsStatus.VALID:
            reason = call.permission_reason or "invalid or missing tool arguments"
            run, events = await self._transition(run, RecordToolResult(run_id=run.run_id, tool_call_id=intent.tool_call_id or "", status="error", result=f"invalid json arguments: {reason}"))
            controller.run = run
            await self._emit(events)
            return run

        tool = self._tool(intent.name)
        if tool is None:
            run, events = await self._transition(run, RecordToolResult(run_id=run.run_id, tool_call_id=intent.tool_call_id or "", status="error", result=_unknown_tool_message(intent.name, self._specs(), self.surface)))
            controller.run = run
            await self._emit(events)
            return run

        error = _schema_error(tool.spec.params, intent.args)
        if error is not None:
            run, events = await self._transition(run, RecordToolResult(run_id=run.run_id, tool_call_id=intent.tool_call_id or "", status="error", result=error))
            controller.run = run
            await self._emit(events)
            return run

        run = await self._apply_command(controller, run, MarkToolValidated(run_id=run.run_id, tool_call_id=intent.tool_call_id or ""))
        analysis = _analyze_shell(tool.spec, intent.args)
        permission = replace(run.permission_ctx, workspace_root=str(self.workspace_root), cwd=str(self.workspace_root))
        sandbox_descriptor = self.sandbox.describe() if self.sandbox is not None and hasattr(self.sandbox, "describe") else _none_descriptor()
        try:
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
        except Exception as exc:  # noqa: BLE001 - 权限求值故障（未知 mode/bug）必须 fail-closed，不得击穿循环（#168）
            run = await self._apply_command(
                controller,
                run,
                MarkToolDenied(run_id=run.run_id, tool_call_id=intent.tool_call_id or "", reason=f"permission evaluation fault; fail-closed deny: {type(exc).__name__}: {exc}"),
            )
            return run
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

    async def _archive_output(self, run: Run, tool_call_id: str, result: ToolResult) -> ToolResult:
        """§7.2 C-1：超预算的工具全文进内容寻址 artifact，prompt 只留有界信封（BLK-10 接线）。"""
        envelope_for = self.output_envelope
        if not callable(envelope_for) or self.artifact_store is None or not isinstance(result.result, str):
            return result  # 未注入就逐字同 P10：不新建第二套归档路径，也不强行归档
        try:
            envelope, _ref, archived = await envelope_for(  # type: ignore[misc]
                result.result,
                store=self.artifact_store,
                run_id=run.run_id,
                tool_call_id=tool_call_id,
                budget=OutputBudget(),
            )
        except Exception:  # noqa: BLE001 - 归档失败降级为有界原样，绝不把全文塑回 prompt（ADR-0019）
            _log.warning("tool output archiving failed; keeping bounded result run=%s call=%s", run.run_id, tool_call_id, exc_info=True)
            return result
        if not archived or not isinstance(envelope, dict):
            return result
        return replace(result, result=envelope)

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
            memory_store=self.memory_store,
            subagent_spawner=self.subagent_spawner,
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
        result = await self._archive_output(run, tool_call_id, result)
        run, events = await self._transition(run, RecordToolResult(run_id=run.run_id, tool_call_id=tool_call_id, status=result.status, result=result.result, display=result.display))
        controller.run = run
        await self._emit(events)
        await self._report_memory_read(run, name, args, result)  # B8：只有真读了记忆文件才打消费点
        await self._checkpoint(run, "post_tool")  # 工具结果已落库 → 快照收窄在途窗口（ADR-0020）
        return run

    async def _apply_command(self, controller: RunController, run: Run, command: Command) -> Run:
        """内部 helper：所有 lifecycle transition 都先落 authority，再 emit。"""
        run, events = await self._transition(run, command)
        controller.run = run
        await self._emit(events)
        return run

    async def _transition(self, run: Run, command: Command, *, source: str = "loop") -> Applied:
        """经唯一咽喉 ``state.transition.apply()`` 落一次迁移：幂等判定 → reduce → 事件。

        B2：受理的命令再写 ``command_window``（canonical digest + 有界 payload）；被拒命令
        （``accepted=False``）不入窗。窗口写失败只告警——队列边缘已做同键异 digest 拒绝。"""
        idem = _transition_key(command, run)
        applied = apply(self.store, run, command, source=source, idempotency_key=idem)
        if applied.accepted and self.store is not None and callable(getattr(self.store, "record_command", None)):
            try:
                await self.store.record_command(
                    applied.run.run_id,
                    applied.run.seq,
                    command.type,
                    window_payload(command),
                    source=source,
                    idem_key=idem,
                    digest=command_digest(command),
                )
            except Exception:  # noqa: BLE001 - 窗口是优化层，失败不得打断单写者循环
                _log.warning("command window record failed run=%s type=%s", applied.run.run_id, command.type, exc_info=True)
        return applied

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
                result = await self._apply_command(controller, run, command)
                await controller.ack_one(command)
                return result
            run = await self._apply_command(controller, run, command)
            await controller.ack_one(command)
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

    async def _settle_open_calls(self, controller: RunController, run: Run) -> Run:
        """把所有仍 OPEN 的工具调用补齐（ADR-0021；ADR-0028 后为一函数两用）。

        - ``awaiting_approval``：等已存在的 request 被 Resolve/Expire/Cancel（不新建 request、不自动放行）。
        - ``ready``/``running``：已批准或曾在跑 → 直接补执行一次（at-least-once；真 exactly-once 靠 P9 claim）。
        - ``pending``/``validated``：崩溃在权限判定前 → **重走 ``_handle_tool_call``（含权限）**，
          绝不绕过 ask（否则 resume 会把未批的危险写静默放行）。
        完成后所有原 OPEN 调用都已闭合，再进入 provider-first 循环，配对得以保持。

        两个安全点共用本函数：① resume 入口（崩溃/审批挂起重建后）；② 每次回发前的配对关卡
        （``_ensure_paired_history``）。原名带 ``resume_`` 前缀会让“循环内不得调用”的误读发生，
        故 ADR-0028 将其改名为中性名（行为逐字不变）。
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
        result = await self._apply_command(controller, run, command)
        await controller.ack_one(command)
        return result

    async def _resume_execute_call(self, controller: RunController, run: Run, call) -> Run:
        """补执行一个已批准（ready）或曾在跑（running）的调用；仅在未 running 时补 MarkToolRunning。"""
        tool = self._tool(call.name)
        if tool is None:
            run, events = await self._transition(run, RecordToolResult(run_id=run.run_id, tool_call_id=call.tool_call_id, status="error", result=f"unknown tool '{call.name}' on resume"))
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

    async def _emit(self, events: Iterable[Envelope]) -> None:
        """把一批事件逐条交给总线（可持久的会落库、live-only 只转发）。"""
        for env in events:
            await self.bus.emit(env)

    async def _live(self, run: Run, turn: int, etype: str, data: dict) -> None:
        # live-only delta：只转发给订阅者，永不持久化（design/01 I3）。
        await self.bus.emit(Envelope(v=1, seq=run.seq, run_id=run.run_id, type=etype, turn=turn, data=data))

    async def _strip_citation(self, run: Run, turn: int, message: Message) -> Message:
        """§6.3：从定稿正文里剥出引用，作为**事件字段**携带，永不回送 provider。

        剥完后的正文才是进 context / 下一轮请求体的内容；引用同时发一条
        条目级 `memory_consumed`（被引用 = 消费；但**命中不算**，见 `_execute_tool` 一侧）。
        """
        blocks: list[ContentBlock] = []
        citation: MemoryCitation | None = None
        for block in message.content:
            if block.type == "text" and block.text and CITATION_OPEN in block.text:
                cleaned, parsed = parse_citation(block.text)
                if parsed is not None:
                    citation = parsed
                blocks.append(replace(block, text=cleaned))
                continue
            blocks.append(block)
        if citation is None:
            return message
        self._turn_citations = citation
        for entry in citation.entries:
            await self._live(
                run,
                turn,
                EventType.MEMORY_CONSUMED,
                {"kind": consumption_kind_for(entry.path), "entry_id": entry.entry_id, "tool_name": None},
            )
        return replace(message, content=tuple(blocks))

    async def _report_memory_read(self, run: Run, name: str, args: object, result: ToolResult) -> None:
        """§6.3 硬规定的另一腿：只有 `read` 类工具**真读了记忆文件**才算消费。

        `memory_search` 命中不发本事件（否则“注入型召回”会把写入噪声率虚假清零）；
        识别不了的路径/工具直接不计数（codex “宁可不计数也不猜”）。
        """
        if self.memory_root is None or name != "read" or result.status != "success" or not isinstance(args, Mapping):
            return
        raw = args.get("file_path")
        if not isinstance(raw, str) or not raw:
            return
        try:
            target = (self.workspace_root / raw).resolve()
            relative = target.relative_to(self.memory_root.resolve())
        except (ValueError, OSError):
            return  # 不在记忆根下（或解析不了）：不计数，不猜
        rel = relative.as_posix()
        offset = args.get("offset")
        limit = args.get("limit")
        # `read` 的 offset 是 **0-based 行下标**，而条目 id 是 1-based 行号：不换算就会错开一行。
        start = (offset if isinstance(offset, int) and offset > 0 else 0) + 1
        count = limit if isinstance(limit, int) and limit > 0 else 1
        await self._live(
            run,
            run.turn,
            EventType.MEMORY_CONSUMED,
            {"kind": consumption_kind_for(rel), "entry_id": f"{rel}:{start}-{start + count - 1}", "tool_name": name},
        )

    async def _build_recall_message(self, run: Run, turn: int) -> Message | None:
        """按最后一个真实 user 原话跑一次召回；返回一条**不入库**的 user-role 前缀消息。

        为什么不写进 Domain_State：召回是“本轮模型看到什么”，不是“发生了什么”（C5）；
        进了事实流就会污染重放与缓存前缀。门控与上限全在端口里（kernel 不判）。
        """
        if self.recall is None:
            return None
        skip, self._recall_skip = self._recall_skip, False
        query = _last_real_user_text(run)
        if not query:
            return None
        block = await self.recall.recall(query, skip=skip)
        if block is None or not block.text or not block.entry_ids:
            return None
        self._recalled_ids.update(block.entry_ids)
        await self._live(run, turn, EventType.MEMORY_INJECTED, dict(block.event_data()))
        return Message(
            id=f"recall:{run.run_id}:{turn}",
            role=Role.USER,
            content=(ContentBlock(type="text", text=block.text),),
            seq=0,
        )

    async def _announce_memory_injection(self, run: Run, turn: int) -> None:
        """首次发出请求前落一条 live-only ``memory_injected``（每 run 一次）。

        “已注入”的口径是“**本轮请求里带了它**”（§6.3 消费可归因的下笔），不是“surface 里有数据”；
        载荷已由装配方裁剪（无正文），本方法不读记忆内容也不做业务判断（C1）。
        """
        if self.memory_injection is None or self._memory_injection_announced:
            return
        self._memory_injection_announced = True
        await self._live(run, turn, EventType.MEMORY_INJECTED, dict(self.memory_injection))

    async def _track_cache_break(self, run: Run, turn: int, request: ProviderRequest) -> None:
        """§6.1 条款 3：三段 hash（system 块 / 工具面 / 历史起点）一变就发 live-only ``cache_break``。

        首轮只建基线（不算断裂）；不开 cache 的来源（side-query）不参与断裂观测。
        载荷只含不可逆 hash 与断点数（条款 1 的预算口径），零正文（C18/C20）。
        """
        if self._cache_ttl is None:
            return
        segments = CacheSegments(
            system=request.system,
            tools=tuple(spec.name for spec in request.tools),
            history_start=request.messages[0].seq if request.messages else None,
        )
        plan = plan_cache(segments)
        reason = break_reason(self._cache_plan, plan)
        self._cache_plan = plan
        if reason is not None:
            await self._live(run, turn, EventType.CACHE_BREAK, plan.event_data(reason=reason))

    async def _maybe_announce_capability(self, run: Run, turn: int) -> None:
        """安全点比对能力名册 generation：变化则发一条 live-only ``tools_changed``（ADR-0046）。

        不 reduce、不入库（TOOLS_CHANGED ∈ LIVE_ONLY）；活 run 的冻结工具面不受影响——事件只告知
        外部观察者“名册变了、下一次 freeze 生效”。kernel 只持注入的 Callable 探针，不 import 能力层（C1）。"""
        if self.capability_probe is None:
            return
        gen = self.capability_probe()
        if gen == self._capability_gen:
            return
        self._capability_gen = gen
        await self._live(run, turn, EventType.TOOLS_CHANGED, {"domain": "tools"})


#: 单条回显基准文本的截断上限（防超大 context 下 SequenceMatcher 退化）。
_ECHO_BASELINE_CAP = 8192


def _prompt_echo_baseline(run: Run) -> list[str]:
    """本轮已/将发给 provider 的可见文本（含工具输出），作为错误回显剥离的基准。

    provider 4xx 常回显请求体；把这些文本交给 :func:`strip_prompt_echo` 后，错误消息中与它们
    的长公共片段会被 ``<prompt>`` 取代（源头去标识，而非依赖下游日志脱敏）。"""
    return [b.text[:_ECHO_BASELINE_CAP] for m in run.context.items for b in m.content if b.type == "text" and b.text]


def _has_text(message: Message) -> bool:
    """消息是否含非空可见文本块。"""
    return any(b.type == "text" and b.text for b in message.content)


def _visible_text(message: Message | None) -> str | None:
    """消息的可见正文（text 块拼接）；空/None 返回 None。"""
    if message is None:
        return None
    text = "".join(b.text or "" for b in message.content if b.type == "text").strip()
    return text or None


def _is_seed_message(message: Message) -> bool:
    """是否为 SeedContext 注入的种子消息（system_marker origin=seed）。"""
    return any(
        b.type == "system_marker" and b.payload and b.payload.get("origin") == "seed" for b in message.content
    )


def _last_real_user_text(run: Run) -> str | None:
    """最近一条真实 user 原话（跳过 seed 消息）；供 settle 判据①。"""
    for message in reversed(run.context.items):
        if message.role is not Role.USER or _is_seed_message(message):
            continue
        text = "".join(b.text or "" for b in message.content if b.type == "text").strip()
        if text:
            return text
    return None


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
    """用 JSON-Schema 校验入参（C8 第一层）；非法则返回可读错误。

    校验**基础设施**故障（远程不可信 schema 含无法解析的 ``$ref``/``$id``、畸形 schema）也归为
    结构化错误返回、**绝不抛出**（#168）：抛出会击穿 drive 循环、run 不落终态。fail-closed——
    无法证明入参合法即按非法处理，工具不执行。
    """
    try:
        validator = Draft202012Validator(params)
        errs = sorted(validator.iter_errors(args), key=lambda e: e.path)
    except Exception as exc:  # noqa: BLE001 - 校验器本身炸（坏 $ref 等）也要 fail-closed 成结构化错误
        return f"invalid arguments: schema validation failed ({type(exc).__name__}: {exc})"
    if not errs:
        return None
    return "invalid arguments: " + "; ".join(e.message for e in errs[:3])
