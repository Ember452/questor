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
from questor.contracts.common import new_id
from questor.contracts.events import EventType, ResolveApproval, SubmitMessage
from questor.contracts.memory import MemoryStorePort
from questor.contracts.ports import ProviderPort, StorePort
from questor.contracts.state_schema import ApprovalStatus, Budget, ContentBlock, Message, Role, RunStatus
from questor.contracts.tool import RunToolSurface
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.kernel.recovery import rebuild_run
from questor.kernel.run_control import RunController
from questor.memory.distill import flush_run_to_daily
from questor.observability.projection import log_envelope
from questor.policy.react_policy import ReActPolicy
from questor.providers.fake import EchoProvider
from questor.providers.litellm_adapter import LiteLLMProvider
from questor.state.domain_state import Run
from questor.surfaces._assembly import assemble_logging
from questor.surfaces.approval import prompt_approval
from questor.surfaces.run_registry import RunRegistry

_TERMINAL_EVENTS = {EventType.RUN_COMPLETED, EventType.RUN_CANCELLED, EventType.RUN_FAILED}

_log = logging.getLogger("questor.cli")

#: run-完成 flush 摘要的字符上限（与 ``reduce`` 的 16KiB 写上限对称，防单次长跑回答撑爆 daily）。
_FLUSH_SUMMARY_MAX_CHARS = 16 * 1024


def _final_answer_text(run: Run) -> str:
    """取最后一条 assistant 消息的可见文本（run 的浓缩回答，非 delta）作为 daily 沉淀素材。"""
    for message in reversed(run.context.items):
        if message.role is Role.ASSISTANT:
            text = "".join(b.text or "" for b in message.content if b.type == "text").strip()
            if text:
                return text
    return ""


def provider_from_env() -> ProviderPort:
    """根据环境变量选 provider：有 model+key 走 LiteLLM，否则离线 Echo。"""
    model = os.environ.get("QUESTOR_MODEL")
    if model and os.environ.get("LITELLM_API_KEY"):
        return LiteLLMProvider(model)
    return EchoProvider()


def sys_stdin_tty() -> bool:
    """stdin 是否接终端（决定能否弹交互审批；非交互一律 fail-closed deny）。"""
    return sys.stdin.isatty()


def _default_registry() -> ToolRegistry:
    """P2 默认内置工具集（注册表只收 available() 为真的，缺 bash 的平台自动隐藏）。"""
    registry = ToolRegistry()
    for tool in (ReadTool(), WriteTool(), EditTool(), ApplyPatchTool(), LsTool(), GlobTool(), GrepTool(), BashTool(), PowerShellTool(), MemorySearchTool()):
        registry.register(tool)
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
    ) -> None:
        self.workspace_root = (workspace_root or Path.cwd()).resolve()
        self.provider = provider or provider_from_env()
        self.system = system
        self.model = model
        self.store = store
        self.memory_store = memory_store
        self.read = ReadTool()
        self.registry = _default_registry()

    def _loop(self, bus: InProcessEventBus, cancel: asyncio.Event, surface: RunToolSurface) -> DefaultTurnLoop:
        """组装一个面向本次 run 的 turn 循环，工具面取自冻结 surface（run 内不变）。"""
        return DefaultTurnLoop(
            provider=self.provider,
            policy=ReActPolicy(),
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
        )

    async def run_once(self, text: str, *, on_delta=None) -> Run:  # noqa: ANN001
        """跑一轮用户输入直到终态：用户文本与审批都以 Command 经 inbox 进入 loop。

        单次 CLI run 若注入了 store 则真实落库（事件 + turn 边界/审批/工具 checkpoint），
        支撑 P3 跨进程 resume；无 store 时退回内存总线（不落库）。surfaces 只持 StorePort
        抽象、不 import 具体 store 实现（S6/T20/C4）。
        """
        bus = InProcessEventBus(self.store)
        cancel = asyncio.Event()
        run = Run(run_id=new_id("run"), budget=Budget())
        surface = self.registry.freeze_for_run(run.run_id)
        loop = self._loop(bus, cancel, surface)
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
        bus = InProcessEventBus(self.store)
        cancel = asyncio.Event()
        tool_surface = self.registry.freeze_for_run(run.run_id)
        loop = self._loop(bus, cancel, tool_surface)
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
            final = await loop.drive_controller(controller)
            await self._flush_run_to_daily(final)
        finally:
            _, still_pending = await asyncio.wait({printer}, timeout=2.0)
            for task in still_pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        return final

    async def _stream(self, queue: asyncio.Queue, on_delta) -> None:  # noqa: ANN001
        """从预挂的订阅队列消费：text_delta 打印/回调，终态后换行退出。"""
        while True:
            env = await queue.get()
            log_envelope(env)
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

    与 ``__main__._amain`` 同为生产入口，因此**共用同一装配口径**（``surfaces._assembly``）——
    以前这里裸调 ``configure_logging()``，既不建文件面也无视 ``QUESTOR_LOG_*`` 与 payload 门
    （Issue #138）。
    """
    assemble_logging()
    try:
        return asyncio.run(interactive())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
