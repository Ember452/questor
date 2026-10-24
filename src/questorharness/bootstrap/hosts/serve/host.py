"""serve 宿主：把 router / broadcaster / authority / 回合任务装到一起。

不变式：宿主**接收**已装配好的 ``RuntimeBundle``，自己不构造 runtime——
这样第二个产品换一份 profile 与注入参数即可复用整个宿主。
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from questorharness.bootstrap.hosts.serve.authority import Authority, PendingPrompt, TurnRecord
from questorharness.bootstrap.hosts.serve.broadcaster import Broadcaster
from questorharness.bootstrap.hosts.serve.routes import Router
from questorharness.bootstrap.hosts.serve.transport import MemoryTransport
from questorharness.bootstrap.hosts.serve.wire import Frame, WireEncoder

if TYPE_CHECKING:
    from questorharness.bootstrap.runtime import RuntimeBundle
    from questorharness.contracts.domain.events import StreamEvent


class ServeHost:
    """一个进程内 serve 宿主。"""

    def __init__(
        self,
        runtime: RuntimeBundle,
        *,
        authority: Authority,
        profile_root: Path,
        profile_id: str = "coding",
    ) -> None:
        self.runtime = runtime
        self.authority = authority
        self.profile_root = Path(profile_root)
        self.profile_id = profile_id
        self.broadcaster = Broadcaster()
        self.encoder = WireEncoder()
        self.router = Router(self)
        self.transport = MemoryTransport(self.router)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._background: set[asyncio.Task[None]] = set()
        authority.set_notifier(self._on_prompt)

    # ---- 生命周期 -------------------------------------------------------
    async def start(self) -> None:
        """启动 runtime（工具、MCP、钩子）。延迟 import 以避开包循环。"""
        from questorharness.bootstrap.runtime import start_runtime

        await start_runtime(self.runtime)

    async def close(self) -> None:
        """取消在跑的回合并关闭 runtime。"""
        from questorharness.bootstrap.runtime import close_runtime

        for task in list(self._tasks.values()):
            task.cancel()
        for task in list(self._background):
            task.cancel()
        await asyncio.gather(*self._tasks.values(), *self._background, return_exceptions=True)
        self._tasks.clear()
        self._background.clear()
        await close_runtime(self.runtime)

    # ---- 回合调度 -------------------------------------------------------
    def start_turn_task(self, record: TurnRecord) -> None:
        """为一条已获租约的提交创建回合任务。"""
        task = asyncio.create_task(self._run_turn(record), name=f"serve-turn-{record.turn_id}")
        self._tasks[record.turn_id] = task

        def _done(finished: asyncio.Task[None]) -> None:
            self._tasks.pop(record.turn_id, None)
            if not finished.cancelled():
                finished.exception()

        task.add_done_callback(_done)

    def cancel_turn(self, turn_id: str, client_id: str) -> bool:
        """取消持有者的回合；非持有者返回 False（由路由翻译成拒绝码）。"""
        record = self.authority.active_turn
        if record is None or record.turn_id != turn_id:
            return False
        if not self.authority.is_owner(turn_id, client_id):
            return False
        task = self._tasks.get(turn_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    async def _run_turn(self, record: TurnRecord) -> None:
        """跑完一个回合：turn_started → 事件流 → turn_done → 释放租约。"""
        from questorharness.bootstrap.runtime import handle_line

        started_at = time.monotonic()
        index = self.authority.next_index()
        await self.broadcaster.publish(
            self.encoder.start_turn(turn_id=record.turn_id, index=index, via="studio")
        )
        cancelled = False
        outcome = "completed"
        try:
            await handle_line(
                self.runtime,
                record.line,
                print_system=self.print_system,
                render_event=self.render_event,
                clear_output=self.clear_output,
            )
        except asyncio.CancelledError:
            cancelled = True
            outcome = "cancelled"
        except Exception as exc:  # noqa: BLE001 - 失败必须落成 turn_done，不能吞掉
            outcome = "failed"
            await self.broadcaster.publish(
                {"kind": "notice", "level": "error", "text": f"{type(exc).__name__}: {exc}"}
            )
        await self.broadcaster.publish(
            {
                "kind": "turn_done",
                "turnId": record.turn_id,
                "cancelled": cancelled,
                "outcome": outcome,
                "durationMs": int((time.monotonic() - started_at) * 1000),
                "checkpointTurn": False,
            }
        )
        self.authority.finish(record.turn_id)
        queued = self.authority.pop_queued()
        if queued is not None:
            self.start_turn_task(queued)

    # ---- 渲染器（注入给 handle_line） -----------------------------------
    async def render_event(self, event: StreamEvent) -> None:
        """把引擎事件编码成帧并广播。"""
        for frame in self.encoder.encode(event):
            await self.broadcaster.publish(frame)

    async def print_system(self, text: str) -> None:
        """系统提示走 notice(info)，与前端分支二消费的一致。"""
        await self.broadcaster.publish({"kind": "notice", "level": "info", "text": text})

    async def clear_output(self) -> None:
        """线协议没有清屏帧；保留钩子以满足 handle_line 的注入契约。"""
        return

    # ---- 提示广播 -------------------------------------------------------
    def _on_prompt(self, prompt: PendingPrompt, subject: str) -> None:
        """authority 打开提示时的同步回调：转成异步广播。"""
        self._spawn(self._publish_prompt(prompt, subject))

    async def _publish_prompt(self, prompt: PendingPrompt, subject: str) -> None:
        """把 approval / ask 广播成对应帧。"""
        if prompt.kind == "approval":
            frame: Frame = {
                "kind": "approval_request",
                "id": prompt.prompt_id,
                "tool": prompt.tool or "unknown",
                "subject": subject,
            }
        else:
            frame = {"kind": "ask_request", "id": prompt.prompt_id, "question": subject}
        await self.broadcaster.publish(frame)

    def _spawn(self, coro: Any) -> None:
        """把协程挂成后台任务，避免被 GC 提前回收。"""
        task = asyncio.create_task(coro)
        self._background.add(task)

        def _done(finished: asyncio.Task[None]) -> None:
            self._background.discard(finished)
            if not finished.cancelled():
                finished.exception()

        task.add_done_callback(_done)
