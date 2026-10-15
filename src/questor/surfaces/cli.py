"""L6 CLI 传输面 —— P1 DoD 主面（design/02 §4；STRUCTURE S6）。

零业务逻辑：它只*装配*注入的各 Port，拼成一个“问一句、流式答一句、可取消”的终端。
所有状态变更仍走 loop -> ``reduce``（C2）。Provider 由配置选：无密钥时 ``EchoProvider``
离线演示，有密钥时 ``LiteLLMProvider`` 走真模型（BYOM）。
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from questor.capabilities.tools.read import ReadTool
from questor.contracts.common import JsonObject, new_id
from questor.contracts.events import EventType
from questor.contracts.ports import ProviderPort
from questor.contracts.state_schema import Budget
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.observability.logging import configure_logging, log_event
from questor.policy.react_policy import ReActPolicy
from questor.providers.fake import EchoProvider
from questor.providers.litellm_adapter import LiteLLMProvider
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import Run


async def terminal_approver(name: str, arguments: JsonObject, reason: str) -> bool:
    """在终端把一个 ``ask`` 解析成人决策（改形自 DeepCode ``harness/approval.py``）。"""
    if not sys_stdin_tty():
        return False  # 非交互 -> fail-closed
    print(f"\n[approval] {name}({arguments}) — {reason}")
    answer = await asyncio.to_thread(input, "allow? [y/n]: ")
    return answer.strip().lower() in {"y", "yes"}


def sys_stdin_tty() -> bool:
    """stdin 是否接终端（决定能否弹审批）。"""
    import sys

    return sys.stdin.isatty()


def provider_from_env() -> ProviderPort:
    """根据环境变量选 provider：有 model+key 走 LiteLLM，否则离线 Echo。"""
    model = os.environ.get("QUESTOR_MODEL")
    if model and os.environ.get("LITELLM_API_KEY"):
        return LiteLLMProvider(model)
    return EchoProvider()


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
        self.registry = {self.read.spec.name: self.read}

    def _loop(self, bus: InProcessEventBus, cancel: asyncio.Event) -> DefaultTurnLoop:
        """组装一个面向本次会话的 turn 循环（P1 只注册 read）。"""
        return DefaultTurnLoop(
            provider=self.provider,
            policy=ReActPolicy(),
            permission=DefaultPermissionEngine(),
            bus=bus,
            tool_for=self.registry.get,
            tools=tuple(self.registry.values()),
            workspace_root=self.workspace_root,
            model=self.model,
            system=self.system,
            approver=terminal_approver,
            cancel_event=cancel,
        )

    async def run_once(self, text: str, *, on_delta=None) -> Run:
        """跑一轮用户输入直到终态，边到边流式 delta。"""
        store = await SQLiteStore(":memory:").connect()
        bus = InProcessEventBus(store)
        cancel = asyncio.Event()
        loop = self._loop(bus, cancel)
        run = Run(run_id=new_id("run"), budget=Budget())
        printer = asyncio.create_task(self._stream(bus, run.run_id, on_delta))
        final = await loop.drive(run, text)
        await printer
        await store.close()
        return final

    async def _stream(self, bus: InProcessEventBus, run_id: str, on_delta) -> None:
        """订阅事件流：text_delta 打印/回调，终态后换行退出。"""
        async for env in bus.subscribe(run_id, 0):
            log_event(env)
            if env.type == EventType.TEXT_DELTA:
                piece = env.data.get("delta", "")
                if on_delta is not None:
                    on_delta(piece)
                else:
                    print(piece, end="", flush=True)
            if env.type in {EventType.RUN_COMPLETED, EventType.RUN_CANCELLED, EventType.RUN_FAILED}:
                print()
                return


async def interactive() -> int:
    """REPL 循环：输一行、流式看答复；Ctrl-D 退出。"""
    configure_logging()
    surface = CliSurface()
    print("questor P1 CLI — type a message (Ctrl-D to exit).")
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
