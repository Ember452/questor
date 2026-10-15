"""L6 CLI 传输面 —— P1 DoD 主面 + P2 HITL（design/02 §4；STRUCTURE S6；ADR-0013）。

零业务逻辑：它只装配注入的 Port，并把用户/审批意图**转成 Command 提交进 RunController**，
绝不直接 reduce。所有状态变更仍由 loop → ``reduce`` 完成（C2）。
Provider 由配置选：无密钥时 ``EchoProvider`` 离线演示，有密钥时 ``LiteLLMProvider`` 走真模型。
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import threading
from pathlib import Path

from questor.capabilities.tools.read import ReadTool
from questor.contracts.common import new_id
from questor.contracts.events import EventType, ResolveApproval, SubmitMessage
from questor.contracts.ports import ProviderPort
from questor.contracts.state_schema import Budget, ContentBlock, Message, Role
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.kernel.run_control import RunController
from questor.observability.logging import configure_logging, log_event
from questor.policy.react_policy import ReActPolicy
from questor.providers.fake import EchoProvider
from questor.providers.litellm_adapter import LiteLLMProvider
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import Run
from questor.surfaces.run_registry import RunRegistry

_TERMINAL_EVENTS = {EventType.RUN_COMPLETED, EventType.RUN_CANCELLED, EventType.RUN_FAILED}


def provider_from_env() -> ProviderPort:
    """根据环境变量选 provider：有 model+key 走 LiteLLM，否则离线 Echo。"""
    model = os.environ.get("QUESTOR_MODEL")
    if model and os.environ.get("LITELLM_API_KEY"):
        return LiteLLMProvider(model)
    return EchoProvider()


def sys_stdin_tty() -> bool:
    """stdin 是否接终端（决定能否弹交互审批；非交互一律 fail-closed deny）。"""
    return sys.stdin.isatty()


async def _confirm_on_tty(args_summary: str, name: str, reason: str) -> bool:
    """在有 TTY 时把审批解析成人决策；用 daemon 线程读 stdin，超时/取消不阻塞退出。"""

    def reader(resolve: callable) -> None:  # noqa: ANN401
        try:
            print(f"\n[approval] {name}({args_summary}) — {reason}")
            answer = input("allow? [y/n]: ")
            resolve(answer.strip().lower() in {"y", "yes"})
        except Exception:  # noqa: BLE001 - 任何读 stdin 失败都视为拒绝（fail-closed）
            resolve(False)

    loop = asyncio.get_running_loop()
    future: asyncio.Future[bool] = loop.create_future()
    # daemon=True：非守护线程会卡住解释器退出（本项目历史 CI 挂死根因）；这里宁可丢弃
    # 一次迟到的按键，也绝不留下非守护 reader 线程。
    threading.Thread(target=reader, args=(lambda value: loop.call_soon_threadsafe(_settle, future, value),), daemon=True).start()
    return await future


def _settle(future: asyncio.Future[bool], value: bool) -> None:
    if not future.done():
        future.set_result(value)


class CliSurface:
    """把 provider/权限/工具/总线/存储装配成可跑的终端会话。"""

    def __init__(
        self,
        *,
        workspace_root: Path | None = None,
        provider: ProviderPort | None = None,
        system: str | None = None,
        model: str = "echo",
    ) -> None:
        self.workspace_root = (workspace_root or Path.cwd()).resolve()
        self.provider = provider or provider_from_env()
        self.system = system
        self.model = model
        self.read = ReadTool()
        self.registry_tools = {self.read.spec.name: self.read}

    def _loop(self, bus: InProcessEventBus, cancel: asyncio.Event) -> DefaultTurnLoop:
        """组装一个面向本次会话的 turn 循环（当前只注册 read）。"""
        return DefaultTurnLoop(
            provider=self.provider,
            policy=ReActPolicy(),
            permission=DefaultPermissionEngine(),
            bus=bus,
            tool_for=self.registry_tools.get,
            tools=tuple(self.registry_tools.values()),
            workspace_root=self.workspace_root,
            model=self.model,
            system=self.system,
            cancel_event=cancel,
        )

    async def run_once(self, text: str, *, on_delta=None) -> Run:  # noqa: ANN001
        """跑一轮用户输入直到终态：用户文本与审批都以 Command 经 inbox 进入 loop。"""
        store = await SQLiteStore(":memory:").connect()
        bus = InProcessEventBus(store)
        cancel = asyncio.Event()
        loop = self._loop(bus, cancel)
        run = Run(run_id=new_id("run"), budget=Budget())
        controller = RunController(run)
        registry = RunRegistry()
        registry.register(controller)
        printer = asyncio.create_task(self._stream(bus, run.run_id, on_delta))
        approver = asyncio.create_task(self._approve(bus, registry, run.run_id))
        try:
            msg = Message(id=new_id("msg"), role=Role.USER, content=(ContentBlock(type="text", text=text),), seq=0)
            await registry.submit(
                run.run_id,
                SubmitMessage(run_id=run.run_id, content=msg),
                source="cli",
                idempotency_key=f"submit:{run.run_id}",
            )
            final = await loop.drive_controller(controller)
        finally:
            for task in (printer, approver):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            await store.close()
        return final

    async def _stream(self, bus: InProcessEventBus, run_id: str, on_delta) -> None:  # noqa: ANN001
        """订阅事件流：text_delta 打印/回调，终态后换行退出。"""
        async for env in bus.subscribe(run_id, 0):
            log_event(env)
            if env.type == EventType.TEXT_DELTA:
                piece = env.data.get("delta", "")
                if on_delta is not None:
                    on_delta(piece)
                else:
                    print(piece, end="", flush=True)
            if env.type in _TERMINAL_EVENTS:
                print()
                return

    async def _approve(self, bus: InProcessEventBus, registry: RunRegistry, run_id: str) -> None:
        """监听 approval_request，只经 registry 提交 ResolveApproval；非交互 → deny（fail-closed）。"""
        interactive = sys_stdin_tty()
        async for env in bus.subscribe(run_id, 0):
            if env.type == EventType.APPROVAL_REQUEST:
                request_id = env.data["request_id"]
                if interactive:
                    allow = await _confirm_on_tty(env.data.get("args_summary", ""), env.data.get("name", ""), env.data.get("reason", ""))
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


async def interactive() -> int:
    """REPL 循环：输一行、流式看答复；Ctrl-D 退出。"""
    configure_logging()
    surface = CliSurface()
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
    """CLI 入口：跑交互 REPL；Ctrl-C 退出码 130。"""
    try:
        return asyncio.run(interactive())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
