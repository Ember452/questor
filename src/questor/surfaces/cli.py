"""L6 CLI 传输面 —— P1 DoD 主面 + P2 HITL（design/02 §4；STRUCTURE S6；ADR-0013）。

零业务逻辑：它只装配注入的 Port，并把用户/审批意图**转成 Command 提交进 RunController**，
绝不直接 reduce。所有状态变更仍由 loop → ``reduce`` 完成（C2）。
Provider 由组合根选择（OPT-6）：无密钥时离线 ``EchoProvider``，有密钥时 ``LiteLLMProvider``。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
from pathlib import Path

from questor.capabilities._host import PluginHost
from questor.capabilities.tools.read import ReadTool
from questor.capabilities.tools.registry import ToolRegistry
from questor.capabilities.toolset import build_tools
from questor.contracts.common import new_id
from questor.contracts.events import EventType, ResolveApproval, SubmitMessage
from questor.contracts.extension import (
    ExtensionDescriptor,
    ExtensionKind,
    HookOutcome,
    InterceptionPoint,
    ObserveChain,
)
from questor.contracts.memory import MemoryStorePort, RecallPort
from questor.contracts.policy import CompactionConfig, PolicyPort, PolicyRef, PolicyTrust
from questor.contracts.ports import ContextAssemblerPort, ProviderPort, StorePort
from questor.contracts.state_schema import ApprovalStatus, Budget, ContentBlock, Message, Role, RunStatus
from questor.contracts.subagent import SubagentSpawnerPort
from questor.contracts.tool import RunToolSurface, Tool
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.kernel.recovery import rebuild_run
from questor.kernel.run_control import RunController
from questor.kernel.seed import SeedRef, build_seed_context, coerce_seed_refs
from questor.kernel.settle import TurnSettler
from questor.memory.distill import flush_run_to_daily
from questor.memory.index import MemoryIndexBlock, admitted, build_index_block
from questor.observability.projection import log_envelope
from questor.policy.null_policy import NullPolicy
from questor.policy.react_policy import ReActPolicy
from questor.policy.registry import ExtensionEntry, ExtensionRegistry, PolicyEntry, PolicyRegistry
from questor.state.domain_state import Run
from questor.surfaces._assembly import (
    DEFAULT_CONTEXT_ASSEMBLER,
    assemble_logging,
    compaction_from_env,
    inject_memory_block,
    payload_preview_from_env,
    reconfigure_output_streams,
)
from questor.surfaces.approval import prompt_approval
from questor.surfaces.mcp_bootstrap import Teardown, discover_mcp_tools
from questor.surfaces.run_registry import RunRegistry

_TERMINAL_EVENTS = {EventType.RUN_COMPLETED, EventType.RUN_CANCELLED, EventType.RUN_FAILED}

_log = logging.getLogger("questor.cli")

#: run-完成 flush 摘要的字符上限（与 ``reduce`` 的 16KiB 写上限对称，防单次长跑回答撑爆 daily）。
_FLUSH_SUMMARY_MAX_CHARS = 16 * 1024

#: P9/ADR-0047：resume 驱动租约 TTL（秒）。单机多进程防同 run 双驱；超 TTL 未释放视为持有者崩溃可被重取。
_RUN_LEASE_TTL_SECONDS = 300.0


async def _noop_teardown() -> None:
    """MCP 未启用时的空 teardown（与 bootstrap 的 teardown 同签名）。"""
    return None


def _final_answer_text(run: Run) -> str:
    """取最后一条 assistant 消息的可见文本（run 的浓缩回答，非 delta）作为 daily 沉淀素材。"""
    for message in reversed(run.context.items):
        if message.role is Role.ASSISTANT:
            text = "".join(b.text or "" for b in message.content if b.type == "text").strip()
            if text:
                return text
    return ""


def provider_from_env() -> ProviderPort:
    """兼容薄壳：provider 选择已上移组合根（OPT-6），这里只委托 providers 层。

    surface 不再自己读 provider env；直接构造 ``CliSurface``（测试/嵌入）仍可用此入口。
    """
    from questor.providers.provider_factory import provider_from_env as _provider_from_env

    return _provider_from_env(payload_preview=payload_preview_from_env())


def sys_stdin_tty() -> bool:
    """stdin 是否接终端（决定能否弹交互审批；非交互一律 fail-closed deny）。"""
    return sys.stdin.isatty()


def _default_registry(profile: str | None = None) -> ToolRegistry:
    """默认内置工具集（OPT-5：profile→tool_id 数据表；注册表只收 available() 为真的）。"""
    registry = ToolRegistry()
    for tool in build_tools(profile):
        registry.register(tool)
    return registry


def _default_policy_registry() -> PolicyRegistry:
    """P9/ADR-0045：默认进程内策略名册（system trust 固定名册，无磁盘扫描）。

    解析发生在装配点（本 surface）、产 PolicyPort 注入 loop；kernel 不 import registry（C1）。
    默认 id=react；null 供降级演示。memory_react 需 loop 供 view.memory（尚未接线，见 #184），
    接线前不入默认名册以免“可选但静默等同 react”的误导；类与直测保留，接线后经 ADR 再加回。"""
    registry = PolicyRegistry(default_id="react")
    registry.register(PolicyEntry(id="react", factory=ReActPolicy, trust=PolicyTrust.SYSTEM))
    registry.register(PolicyEntry(id="null", factory=NullPolicy, trust=PolicyTrust.SYSTEM))
    return registry


def _settle_extension_entry(settler: TurnSettler | None) -> ExtensionEntry:
    """把 TurnSettler 包装成 **Stop 点位的单条 OBSERVE 条目**（B5；§5.1 第 13 行）。

    ``settler=None`` 用于 inspect：只声明形状，不执行写回。
    """

    async def _hook(payload: object) -> HookOutcome:
        if settler is not None:
            await settler.settle(payload)  # type: ignore[arg-type]
        return HookOutcome()

    descriptor = ExtensionDescriptor(
        id="settle-turn",
        kind=ExtensionKind.OBSERVE,
        at=InterceptionPoint.STOP.value,
        priority=100,
    )
    return ExtensionEntry(descriptor, lambda: _hook)


def memory_root_of(memory_store: MemoryStorePort | None) -> Path | None:
    """从注入的记忆端口取真源根目录（只读属性）；拿不到就算“不可识别”，不猜。"""
    root = getattr(memory_store, "memory_root", None)
    return Path(root) if isinstance(root, (str, Path)) else None


def inspect_extensions_text() -> str:
    """无 store/无日志装配的装配链文本（``--inspect-extensions`` 用）。"""
    registry = ExtensionRegistry()
    for entry in _default_policy_registry().all_entries():
        registry.register(entry)
    registry.register(_settle_extension_entry(None))
    return registry.render_chain()


class CliSurface:
    """把 provider/权限/工具/总线/存储装配成可跑的终端会话。"""

    def __init__(
        self,
        *,
        workspace_root: Path | None = None,
        provider: ProviderPort | None = None,
        system: str | None = None,
        model: str = "echo",
        store: StorePort | None = None,
        memory_store: MemoryStorePort | None = None,
        skills_dir: Path | None = None,
        mcp_json_path: Path | None = None,
        log_dir: Path | None = None,
        policy_id: str = "react",
        ab_table: dict[str, int] | None = None,
        compaction: CompactionConfig | None = None,
        process_runner: object | None = None,
        artifact_store: object | None = None,
        sandbox: object | None = None,
        context_assembler: ContextAssemblerPort | None = None,
        memory_index_enabled: bool = False,
        recall: RecallPort | None = None,
    ) -> None:
        self.workspace_root = (workspace_root or Path.cwd()).resolve()
        self.provider = provider or provider_from_env()
        self.model = model
        self.store = store
        self.memory_store = memory_store
        # exec/写围栏/归档三件套由组合根注入（#154）；None → loop 走 fail-closed（无 runner 则 run_process 拒）。
        self.process_runner = process_runner
        self.artifact_store = artifact_store
        self.sandbox = sandbox
        self.mcp_json_path = mcp_json_path  # None → MCP 禁用（不改动既有 run 行为）
        self.log_dir = log_dir
        self.read = ReadTool()
        self.registry = _default_registry()
        # P9/ADR-0045：策略经进程内 registry 按 run 解析（fail-open 默认 react）；不再硬编码 ReActPolicy。
        self.policy_registry = _default_policy_registry()
        self.policy_id = policy_id
        self.ab_table = ab_table
        # P10/Major-1：可恢复压缩旋钮由组合根注入（显式传参优先，否则读 QUESTOR_COMPACTION env）。
        # None=默认不压缩（向后兼容）；非 None 则 _loop 透传给 DefaultTurnLoop，生产 run 达阈会真压缩。
        self.compaction = compaction if compaction is not None else compaction_from_env()
        # P9/ADR-0046：能力热插拔宿主（统一 init/teardown + 熔断隔离）；generation 与工具注册表共构探针。
        self.plugin_host = PluginHost()
        # 技能生效（DoD①）：system prompt 的「system + skills catalog」拼接已外提为 context_assembler
        # 接缝（OPT-12a）：默认实现逐字节等于历史在本类的内联拼接；skills_dir=None 时 catalog 为空、
        # system 原样（None 仍 None）——不影既有 run。描述已在 catalog 内过 `bound_description` 有界。
        assembler = context_assembler if context_assembler is not None else DEFAULT_CONTEXT_ASSEMBLER
        self.system = assembler.assemble(system, skills_dir)
        # B7（§6.1 档1）：记忆索引段。**默认关**，由生产组合根翻 on（D3）；开时每次 run 开始前
        # 从真源 `MEMORY.md` 重建有界索引，作为定界静态子段接到 system 末尾（正文不进召回位）。
        # `self.system` 本身**不动**：它仍是 skills 装配结果，既有逐字节 golden 契约零改动。
        self.memory_index_enabled = memory_index_enabled
        self.memory_index: MemoryIndexBlock | None = None
        # B8：召回端口由**组合根**注入（默认 None = 不召回，既有直连构造逐字不变）。
        # surface 不自己 new 实现、不读 embedding env：它只是把端口递给 loop。
        self.recall = recall

    async def refresh_memory_index(self) -> None:
        """从记忆真源重建档1 索引段（未开启/无 store/读失败 → `None` = 本轮不注入）。

        只在异步入口（run_once / resume / HTTP start_run）调用：IO 经注入的 MemoryStorePort，
        surface 不碰文件、不碰库实现（C4）。"""
        if not self.memory_index_enabled or self.memory_store is None:
            self.memory_index = None
            return
        try:
            core = await self.memory_store.read_memory_text("MEMORY.md")
        except Exception:  # noqa: BLE001 - 索引不可用是合法降级（不注入），不得拖垮装配
            _log.warning("memory index refresh failed; running without the index section", exc_info=True)
            self.memory_index = None
            return
        block = build_index_block(core)
        # 四道约束缺一即整体降级为“不进 system”（§6.1）：宁可不注入也不破 prompt cache 纪律。
        self.memory_index = block if admitted(block) else None

    def _resolve_for_run(self, run_id: str) -> tuple[PolicyPort, PolicyRef]:
        """按 run 解析策略（fail-open 回落默认）→ (PolicyPort, 冻结 PolicyRef)。"""
        return self.policy_registry.resolve_or_default(self.policy_id, split_key=run_id, ab_table=self.ab_table)

    def capability_probe(self) -> int:
        """能力名册合成版本：工具注册表 + 插件宿主 generation 之和（注入 loop 探测热插拔→发 tools_changed）。"""
        return self.registry.generation + self.plugin_host.generation

    def build_extension_registry(self, settler: TurnSettler | None = None) -> ExtensionRegistry:
        """本 surface 的装配视图：策略名册 + Stop 观察者（inspect 与 _loop 共用同一形状）。"""
        registry = ExtensionRegistry()
        for entry in self.policy_registry.all_entries():
            registry.register(entry)
        registry.register(_settle_extension_entry(settler))
        return registry

    def inspect_extensions(self) -> str:
        """稳定 ASCII 装配链（``--inspect-extensions`` 用；不触 store/loop）。"""
        return inspect_extensions_text()

    def _loop(self, bus: InProcessEventBus, cancel: asyncio.Event, surface: RunToolSurface, subagent_spawner: SubagentSpawnerPort | None = None, *, run_id: str = "", session_id: str = "") -> DefaultTurnLoop:
        """组装一个面向本次 run 的 turn 循环，工具面取自冻结 surface（run 内不变）。

        ``subagent_spawner`` 由组合根注入（P8 多 agent）；未注入时单 run 行为逐字不变。
        策略经 PolicyRegistry 按 run 解析（P9）：活 run 用其已注入端口、换 registry 只影响新 run。
        B6：本入口注册同一 TurnSettler（CLI 的四驱动点共用），记忆写回只经 WriteMemory。"""
        policy, _ref = self._resolve_for_run(run_id)
        settler = TurnSettler(bus, self.store, self.memory_store, session_id or f"sess:{run_id}")
        registry = self.build_extension_registry(settler)
        stop: ObserveChain = registry.resolve_observe(InterceptionPoint.STOP.value)
        # B7：索引段作为定界静态子段接到本 run 的 system 末尾（一次性、跨 turn 不变 → 可入 cache 前缀）。
        block = self.memory_index
        system = inject_memory_block(self.system, (lambda: block.text) if block is not None else None)
        return DefaultTurnLoop(
            provider=self.provider,
            policy=policy,
            permission=DefaultPermissionEngine(),
            bus=bus,
            tool_for=surface.tool_for,
            tools=surface.tools,
            surface=surface,
            store=self.store,
            memory_store=self.memory_store,
            workspace_root=self.workspace_root,
            model=self.model,
            system=system,
            cancel_event=cancel,
            subagent_spawner=subagent_spawner,
            capability_probe=self.capability_probe,
            compaction=self.compaction,
            process_runner=self.process_runner,
            artifact_store=self.artifact_store,
            sandbox=self.sandbox,
            stop=stop,
            memory_injection=block.event_data() if block is not None else None,
            recall=self.recall,
            # 只用于“这次 Read 读的是不是记忆文件”的判定（不传句柄、不代工具读写）。
            memory_root=memory_root_of(self.memory_store),
        )

    async def _discover_mcp(self, run_id: str) -> tuple[list[Tool], Teardown]:
        """若配了 mcp.json 则 per-run 起 MCP 连接发远程工具；否则空+noop teardown（不改动既有行为）。"""
        if self.mcp_json_path is None:
            return [], _noop_teardown
        log_dir = self.log_dir or (self.workspace_root / ".questor" / "logs")
        return await discover_mcp_tools(mcp_json=self.mcp_json_path, log_dir=log_dir, run_id=run_id)

    def _freeze_surface(self, run_id: str, extra_tools: list[Tool]) -> RunToolSurface:
        """冻结本次 run 的工具面：内置工具 + 本次发现的 MCP 远程工具（per-run 拼，run 内不变）。"""
        if not extra_tools:
            return self.registry.freeze_for_run(run_id)
        run_registry = ToolRegistry()
        for tool in self.registry.list_available():
            run_registry.register(tool)
        for tool in extra_tools:
            run_registry.register(tool)  # 命名冲突由 registry first-writer-wins 拒盖（C21）
        return run_registry.freeze_for_run(run_id)

    async def run_once(
        self,
        text: str,
        *,
        on_delta=None,  # noqa: ANN001
        session_id: str | None = None,
        seed_refs: object | None = None,
    ) -> Run:
        """跑一轮用户输入直到终态：用户文本与审批都以 Command 经 inbox 进入 loop。

        单次 CLI run 若注入了 store 则真实落库（事件 + turn 边界/审批/工具 checkpoint），
        支撑 P3 跨进程 resume；无 store 时退回内存总线（不落库）。surfaces 只持 StorePort
        抽象、不 import 具体 store 实现（S6/T20/C4）。

        B4：给 ``session_id`` 时先确保会话行、绑定 run→session，并注入有界 SeedContext；
        不给时新建 session 行（单次 run 也落一行），不 seed。
        """
        bus = InProcessEventBus(self.store)
        # 带外投影改挂 bus 级唯一只读订阅（ADR-0033）：不再逐消费者调 log_envelope，
        # 与 run 内 printer/approver 两个订阅队列并存也不会双投。
        bus.add_observer(log_envelope)
        await self.refresh_memory_index()  # B7：真源为文件，逐 run 重建索引（写入后下一轮可见）
        cancel = asyncio.Event()
        run_id = new_id("run")
        _policy, ref = self._resolve_for_run(run_id)
        run = Run(run_id=run_id, budget=Budget(), policy_ref=ref)
        sid, seed_requested = await self._prepare_session(run_id, session_id)
        seed_message = await self._seed_message(run, sid, seed_requested, seed_refs)
        mcp_tools, mcp_teardown = await self._discover_mcp(run.run_id)
        surface = self._freeze_surface(run.run_id, mcp_tools)
        loop = self._loop(bus, cancel, surface, run_id=run.run_id, session_id=sid)
        controller = RunController(run, queue=self.store, session_id=sid)
        registry = RunRegistry()
        registry.register(controller)
        # 先同步挂上两个订阅队列（start drive 之前），保证不丢最早的 text_delta/approval_request；
        # 单次 CLI run 不需跨进程重放，故不注入具体 store（surfaces 不依赖 store 实现，S6/T20）。
        printer_queue = bus.add_subscriber(run.run_id)
        approver_queue = bus.add_subscriber(run.run_id)
        printer = asyncio.create_task(self._stream(printer_queue, on_delta))
        approver = asyncio.create_task(self._approve(approver_queue, registry, run.run_id))
        try:
            if seed_message is not None:
                await registry.submit(
                    run.run_id,
                    SubmitMessage(run_id=run.run_id, content=seed_message),
                    source="cli",
                    idempotency_key=f"seed:{run.run_id}",
                )
            msg = Message(id=new_id("msg"), role=Role.USER, content=(ContentBlock(type="text", text=text),), seq=0)
            await registry.submit(
                run.run_id,
                SubmitMessage(run_id=run.run_id, content=msg),
                source="cli",
                idempotency_key=f"submit:{run.run_id}",
            )
            final = await loop.drive_controller(controller)
        finally:
            # 两个消费者都会自然收到终态帧并退出（queue 里已有 terminal）；超时才强收。
            _, still_pending = await asyncio.wait({printer, approver}, timeout=2.0)
            for task in still_pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            await mcp_teardown()  # per-run MCP 连接与 stderr 句柄收尾（不留悬空子进程/文件）
        return final

    async def _prepare_session(self, run_id: str, session_id: str | None) -> tuple[str, bool]:
        """确保会话行 + 绑定 run；返回 (session_id, 是否请求 seed)。无 store 时退化为内存会话。"""
        store = self.store
        if store is not None and callable(getattr(store, "create_session", None)):
            if session_id:
                sid = (await store.ensure_session(session_id))["session_id"]  # type: ignore[attr-defined]
            else:
                sid = await store.create_session(  # type: ignore[attr-defined]
                    model=self.model, workspace_root=str(self.workspace_root)
                )
            await store.bind_run_session(run_id, sid)  # type: ignore[attr-defined]
            return str(sid), bool(session_id)
        return session_id or f"sess:{run_id}", bool(session_id)

    async def _seed_message(self, run: Run, sid: str, requested: bool, raw_refs: object | None):  # noqa: ANN201
        """按请求构造 seed 消息；无 session_id 时不 seed（保持历史行为）。"""
        if not requested:
            return None
        refs: tuple[SeedRef, ...] = coerce_seed_refs(raw_refs, sid)
        store = self.store if callable(getattr(self.store, "session_transcript", None)) else None
        return await build_seed_context(store, sid, refs=refs, status=run.status)


    async def _flush_run_to_daily(self, run: Run) -> None:
        """run **成功完成**边界的 episodic→daily 沉淀（产品化“记住”写入触发器）。

        ADR-0025：经注入的 ``MemoryStorePort`` 离线收口、不进热 loop；幂等（run_id 键）使重投安全。
        best-effort：失败只告警不拖垮已完成 run（主回答已流式完）。**仅 COMPLETED 才写**（failed/cancelled
        的残缺/错误输出不污染长期记忆）；无 memory_store / 无回答 → 不写；摘要按上限截断。"""
        if self.memory_store is None or run.status is not RunStatus.COMPLETED:
            return
        summary = _final_answer_text(run)[:_FLUSH_SUMMARY_MAX_CHARS]
        if not summary:
            return
        try:
            await flush_run_to_daily(self.memory_store, summary_text=summary, run_id=run.run_id)
        except Exception:  # noqa: BLE001 - 记忆沉淀失败不得拖垮已完成 run；run_id 幂等键使重投安全
            _log.warning("run-completion daily flush failed for run %s", run.run_id, exc_info=True)

    async def _renew_lease_loop(self, run_id: str, holder: str) -> None:
        """每 ttl/2 续租，保长 CLI resume 不因超 TTL 被过期抢占（C2 单写者，track4 BLK-2）。"""
        interval = max(1.0, _RUN_LEASE_TTL_SECONDS / 2)
        try:
            while True:
                await asyncio.sleep(interval)
                if self.store is None or not await self.store.renew_lease(run_id, holder, 1):
                    return
        except asyncio.CancelledError:
            pass

    async def resume(self, run_id: str) -> Run | None:
        """从持久态续跑一个被 kill/重启的 run（P3 T12，ADR-0021）。

        surfaces 零业务：只重建 + 把已存在的挂起审批经同一 Command Inbox 提交 + 交回
        唯一 loop；真正的未闭合 tool_use 补齐/re-dispatch 由 kernel 的 loop 完成。无 store 无法续跑。
        """
        if self.store is None:
            raise RuntimeError("resume needs a persistent StorePort (set CliSurface(store=...))")
        run = await rebuild_run(self.store, run_id)
        if run is None:
            return None
        # P9/ADR-0047：resume 前取 run 租约——防两进程/两次 resume 并发同 run 双驱（单机多进程单写者）。
        # 取不到=他人持有 → 诚实拒绝（返回 None），绝不双驱。跨机抢锁属 C12 天花板（本 Phase 不做）。
        holder = f"cli-resume:{os.getpid()}:{new_id('drv')}"
        if not await self.store.acquire_lease(run_id, holder, 1, ttl_seconds=_RUN_LEASE_TTL_SECONDS):
            _log.warning("resume refused: run %s lease held by another driver (single-writer, ADR-0047)", run_id)
            return None
        bus = InProcessEventBus(self.store)
        bus.add_observer(log_envelope)  # bus 级唯一投影订阅（ADR-0033）
        await self.refresh_memory_index()  # B7：resume 同样重建索引（不拿 stale 段进新 turn）
        cancel = asyncio.Event()
        tool_surface = self.registry.freeze_for_run(run.run_id)
        sid = await self.store.run_session(run_id) if callable(getattr(self.store, "run_session", None)) else None
        loop = self._loop(bus, cancel, tool_surface, run_id=run.run_id, session_id=sid or f"sess:{run_id}")
        controller = RunController(run, queue=self.store, session_id=sid or f"sess:{run_id}")
        interactive = sys_stdin_tty()
        printer_queue = bus.add_subscriber(run.run_id)
        printer = asyncio.create_task(self._stream(printer_queue, None))
        for approval in run.permission_ctx.approvals:
            if approval.status is ApprovalStatus.PENDING:
                if interactive:
                    decision = "allow" if await prompt_approval(approval.args_summary, "", approval.reason) else "deny"
                else:
                    decision = "deny"  # 非交互 fail-closed
                await controller.submit(
                    ResolveApproval(run_id=run.run_id, request_id=approval.request_id, decision=decision, decided_by="cli-resume"),
                    source="cli",
                    idempotency_key=approval.request_id,
                )
        try:
            renew_task = asyncio.create_task(self._renew_lease_loop(run_id, holder))
            try:
                final = await loop.drive_controller(controller)
            finally:
                renew_task.cancel()
        finally:
            _, still_pending = await asyncio.wait({printer}, timeout=2.0)
            for task in still_pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            await self.store.release_lease(run_id, holder, 1)
        return final

    async def _stream(self, queue: asyncio.Queue, on_delta) -> None:  # noqa: ANN001
        """从预挂的订阅队列消费：text_delta 打印/回调，终态后换行退出。

        不再在此逐消费者调 ``log_envelope``——带外投影已收口到 bus 级唯一只读订阅（ADR-0033 / D-P7-A）。
        """
        while True:
            env = await queue.get()
            if env.type == EventType.TEXT_DELTA:
                piece = env.data.get("delta", "")
                if on_delta is not None:
                    on_delta(piece)
                else:
                    print(piece, end="", flush=True)
            if env.type in _TERMINAL_EVENTS:
                print()
                return

    async def _approve(self, queue: asyncio.Queue, registry: RunRegistry, run_id: str) -> None:
        """监听 approval_request，只经 registry 提交 ResolveApproval；非交互 → deny（fail-closed）。"""
        interactive = sys_stdin_tty()
        while True:
            env = await queue.get()
            if env.type == EventType.APPROVAL_REQUEST:
                request_id = env.data["request_id"]
                if interactive:
                    allow = await prompt_approval(env.data.get("args_summary", ""), env.data.get("name", ""), env.data.get("reason", ""))
                    decision = "allow" if allow else "deny"
                else:
                    decision = "deny"
                await registry.submit(
                    run_id,
                    ResolveApproval(run_id=run_id, request_id=request_id, decision=decision, decided_by="cli"),
                    source="cli",
                    idempotency_key=request_id,
                )
            if env.type in _TERMINAL_EVENTS:
                return


async def interactive(surface: CliSurface | None = None) -> int:
    """REPL 循环：输一行、流式看答复；Ctrl-D 退出。store 由组合根（``__main__``）注入。

    日志装配责任已上移组合根（DESIGN §11）：本函数不再自调 ``configure_logging``；
    直接调本函数的入口/测试需自行显式装配。

    B4：会话连续——store 支持 sessions 时整个 REPL 复用同一 session_id（每轮 run 注入 seed）。
    """
    surface = surface or CliSurface()
    session_id = new_id("sess") if callable(getattr(surface.store, "create_session", None)) else None
    print("questor CLI — type a message (Ctrl-D to exit).")
    while True:
        try:
            text = await asyncio.to_thread(input, "\n> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not text.strip():
            continue
        await surface.run_once(text, session_id=session_id)
    return 0


def main() -> int:
    """独立模块入口（``python -m questor.surfaces.cli``）：跑交互 REPL；Ctrl-C 退出码 130。

    与 ``__main__._amain`` **共用同一组合根**（``composition.build_app``，#161）：model/store/memory/
    skills/MCP/exec 三件套一律同口径装配，不再出现"第二入口静默丢失持久化与模型路由"。
    局部 import composition 避开模块级 import 环（composition→cli）。
    """
    from questor.composition import build_app, close_app

    async def _run() -> int:
        reconfigure_output_streams()  # 先于一切输出把 stdout/stderr 重配为 UTF-8 兜底（#180）
        assemble_logging()
        app = await build_app()
        try:
            return await interactive(app.surface)
        finally:
            await close_app(app)

    try:
        return asyncio.run(_run())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
