"""L6 CLI 传输面 —— P1 DoD 主面 + P2 HITL（design/02 §4；STRUCTURE S6；ADR-0013）。

零业务逻辑：它只装配注入的 Port，并把用户/审批意图**转成 Command 提交进 RunController**，
绝不直接 reduce。所有状态变更仍由 loop → ``reduce`` 完成（C2）。
Provider 由配置选：无密钥时 ``EchoProvider`` 离线演示，有密钥时 ``LiteLLMProvider`` 走真模型。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
from pathlib import Path

from questor.capabilities._host import PluginHost
from questor.capabilities.subagent.delegate import DelegateTool
from questor.capabilities.tools.apply_patch import ApplyPatchTool
from questor.capabilities.tools.bash import BashTool
from questor.capabilities.tools.edit import EditTool
from questor.capabilities.tools.glob import GlobTool
from questor.capabilities.tools.grep import GrepTool
from questor.capabilities.tools.ls import LsTool
from questor.capabilities.tools.memory_search import MemorySearchTool
from questor.capabilities.tools.powershell import PowerShellTool
from questor.capabilities.tools.read import ReadTool
from questor.capabilities.tools.registry import ToolRegistry
from questor.capabilities.tools.write import WriteTool
from questor.config.model import load_config
from questor.contracts.common import new_id
from questor.contracts.events import EventType, ResolveApproval, SubmitMessage
from questor.contracts.memory import MemoryStorePort
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
from questor.memory.distill import flush_run_to_daily
from questor.observability.projection import log_envelope
from questor.policy.null_policy import NullPolicy
from questor.policy.react_policy import ReActPolicy
from questor.policy.registry import PolicyEntry, PolicyRegistry
from questor.providers.fake import EchoProvider
from questor.providers.litellm_adapter import LiteLLMProvider
from questor.state.domain_state import Run
from questor.surfaces._assembly import (
    DEFAULT_CONTEXT_ASSEMBLER,
    assemble_logging,
    compaction_from_env,
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
    """根据环境变量选 provider：有 model+key 走 LiteLLM，否则离线 Echo。

    env 读取与判定口径收口在 ``config``（OPT-3 c2）：``model`` 保留原样（未设 = None）、
    密钥只判存在；无 model 或无 key 一律 Echo（与历史逐字等价）。
    """
    cfg = load_config()
    if cfg.llm.model and cfg.llm.has_litellm_key:
        # P10/ADR-0049：preview 预算由组合根解析注入（None=零原文默认）；非空才落独立 llm 通道。
        return LiteLLMProvider(cfg.llm.model, payload_preview=payload_preview_from_env())
    return EchoProvider()


def sys_stdin_tty() -> bool:
    """stdin 是否接终端（决定能否弹交互审批；非交互一律 fail-closed deny）。"""
    return sys.stdin.isatty()


def _default_registry() -> ToolRegistry:
    """P2 默认内置工具集（注册表只收 available() 为真的，缺 bash 的平台自动隐藏）。"""
    registry = ToolRegistry()
    for tool in (ReadTool(), WriteTool(), EditTool(), ApplyPatchTool(), LsTool(), GlobTool(), GrepTool(), BashTool(), PowerShellTool(), MemorySearchTool(), DelegateTool()):
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

    def _resolve_for_run(self, run_id: str) -> tuple[PolicyPort, PolicyRef]:
        """按 run 解析策略（fail-open 回落默认）→ (PolicyPort, 冻结 PolicyRef)。"""
        return self.policy_registry.resolve_or_default(self.policy_id, split_key=run_id, ab_table=self.ab_table)

    def capability_probe(self) -> int:
        """能力名册合成版本：工具注册表 + 插件宿主 generation 之和（注入 loop 探测热插拔→发 tools_changed）。"""
        return self.registry.generation + self.plugin_host.generation

    def _loop(self, bus: InProcessEventBus, cancel: asyncio.Event, surface: RunToolSurface, subagent_spawner: SubagentSpawnerPort | None = None, *, run_id: str = "") -> DefaultTurnLoop:
        """组装一个面向本次 run 的 turn 循环，工具面取自冻结 surface（run 内不变）。

        ``subagent_spawner`` 由组合根注入（P8 多 agent）；未注入时单 run 行为逐字不变。
        策略经 PolicyRegistry 按 run 解析（P9）：活 run 用其已注入端口、换 registry 只影响新 run。"""
        policy, _ref = self._resolve_for_run(run_id)
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
            system=self.system,
            cancel_event=cancel,
            subagent_spawner=subagent_spawner,
            capability_probe=self.capability_probe,
            compaction=self.compaction,
            process_runner=self.process_runner,
            artifact_store=self.artifact_store,
            sandbox=self.sandbox,
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

    async def run_once(self, text: str, *, on_delta=None) -> Run:  # noqa: ANN001
        """跑一轮用户输入直到终态：用户文本与审批都以 Command 经 inbox 进入 loop。

        单次 CLI run 若注入了 store 则真实落库（事件 + turn 边界/审批/工具 checkpoint），
        支撑 P3 跨进程 resume；无 store 时退回内存总线（不落库）。surfaces 只持 StorePort
        抽象、不 import 具体 store 实现（S6/T20/C4）。
        """
        bus = InProcessEventBus(self.store)
        # 带外投影改挂 bus 级唯一只读订阅（ADR-0033）：不再逐消费者调 log_envelope，
        # 与 run 内 printer/approver 两个订阅队列并存也不会双投。
        bus.add_observer(log_envelope)
        cancel = asyncio.Event()
        run_id = new_id("run")
        _policy, ref = self._resolve_for_run(run_id)
        run = Run(run_id=run_id, budget=Budget(), policy_ref=ref)
        mcp_tools, mcp_teardown = await self._discover_mcp(run.run_id)
        surface = self._freeze_surface(run.run_id, mcp_tools)
        loop = self._loop(bus, cancel, surface, run_id=run.run_id)
        controller = RunController(run)
        registry = RunRegistry()
        registry.register(controller)
        # 先同步挂上两个订阅队列（start drive 之前），保证不丢最早的 text_delta/approval_request；
        # 单次 CLI run 不需跨进程重放，故不注入具体 store（surfaces 不依赖 store 实现，S6/T20）。
        printer_queue = bus.add_subscriber(run.run_id)
        approver_queue = bus.add_subscriber(run.run_id)
        printer = asyncio.create_task(self._stream(printer_queue, on_delta))
        approver = asyncio.create_task(self._approve(approver_queue, registry, run.run_id))
        try:
            msg = Message(id=new_id("msg"), role=Role.USER, content=(ContentBlock(type="text", text=text),), seq=0)
            await registry.submit(
                run.run_id,
                SubmitMessage(run_id=run.run_id, content=msg),
                source="cli",
                idempotency_key=f"submit:{run.run_id}",
            )
            final = await loop.drive_controller(controller)
            await self._flush_run_to_daily(final)
        finally:
            # 两个消费者都会自然收到终态帧并退出（queue 里已有 terminal）；超时才强收。
            _, still_pending = await asyncio.wait({printer, approver}, timeout=2.0)
            for task in still_pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            await mcp_teardown()  # per-run MCP 连接与 stderr 句柄收尾（不留悬空子进程/文件）
        return final

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
        cancel = asyncio.Event()
        tool_surface = self.registry.freeze_for_run(run.run_id)
        loop = self._loop(bus, cancel, tool_surface, run_id=run.run_id)
        controller = RunController(run)
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
                await self._flush_run_to_daily(final)
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
    """
    surface = surface or CliSurface()
    print("questor CLI — type a message (Ctrl-D to exit).")
    while True:
        try:
            text = await asyncio.to_thread(input, "\n> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not text.strip():
            continue
        await surface.run_once(text)
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
