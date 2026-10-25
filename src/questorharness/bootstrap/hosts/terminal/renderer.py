"""终端渲染器：wire 帧 → 视图模型 → 图元，并把审批/提问回灌成 HTTP 调用。

属于呈现层：只消费 serve 契约，不持有会话事实（plan03 §2.1 不变量）。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from rich.console import Console

from questorharness.bootstrap.hosts.serve import terminal_theme as theme
from questorharness.bootstrap.hosts.serve.host import ServeHost
from questorharness.bootstrap.hosts.terminal import approval as limits
from questorharness.bootstrap.hosts.terminal import cards, footer, strings
from questorharness.bootstrap.hosts.terminal import wire_view as view

PREFIX = "/rt/r1"


def frame_from_sse(block: bytes) -> dict[str, Any] | None:
    """从一条 SSE 事件块里取出 data 帧。"""
    for line in block.splitlines():
        if line.startswith(b"data: "):
            try:
                parsed = json.loads(line[len(b"data: ") :])
            except json.JSONDecodeError:
                return None
            return parsed if isinstance(parsed, dict) else None
    return None


class TerminalRenderer:
    """把 wire 帧渲染到终端，并把审批/提问回灌成 HTTP 调用。"""

    def __init__(self, host: ServeHost, console: Console, *, profile_name: str = "?") -> None:
        self._host = host
        self._console = console
        self._profile_name = profile_name
        self._streaming = False
        self._streamed_text = False
        self._busy = False
        self._queue_depth = 0
        self._pending_turns = 0
        self._usage: view.UsageVM | None = None
        self.done = asyncio.Event()

    @property
    def busy(self) -> bool:
        """当前是否有回合在跑（决定 Ctrl-C 是取消还是清行）。"""

        return self._busy

    @property
    def pending_turns(self) -> int:
        """已提交但未收到 turn_done 的回合数（退出前要收干净）。"""

        return self._pending_turns

    def expect_turn(self) -> None:
        """记一个已受理的提交；turn_done 时清除。"""

        self._pending_turns += 1

    def note_queued(self) -> None:
        """服务端排上了：立即给一行可见回执，用户才知道没丢。"""

        self._queue_depth = 1
        self._console.print(strings.QUEUED, style=theme.DIM)
        self._console.print(self._footer())

    def note_cancel_requested(self) -> None:
        """已发 /cancel：回合结不结束由服务端决定，但用户要知道请求已送达。"""

        self._console.print(strings.CANCEL_SENT, style=theme.WARN)

    def show(self, text: str) -> None:
        """终端本地提示（面板清单/空态/取数据失败）。"""

        self._console.print(text, style=theme.DIM)

    async def consume(self, stream: AsyncIterator[bytes]) -> None:
        """持续消费 SSE 字节流。"""
        buffer = b""
        async for chunk in stream:
            buffer += chunk
            while b"\n\n" in buffer:
                block, buffer = buffer.split(b"\n\n", 1)
                if not block.startswith(b"id:"):
                    continue
                frame = frame_from_sse(block)
                if frame is not None:
                    await self._render(frame)
                # 不能在 turn_done 后 return：交互模式要连续多轮；单次 prompt
                # 由调用方 done.wait() 收尾，两种模式都靠 finally 的 cancel 退订。

    async def _render(self, frame: dict[str, Any]) -> None:
        """帧 → 视图模型 → 图元；审批/提问就地询问。渲染细节全在 `terminal/`。"""
        item = view.view_of(frame)
        if isinstance(item, view.TextItem):
            # 流式正文按原样输出（逐字 markdown 重排会把屏幕抖成碎行）。
            self._console.print(item.text, end="", soft_wrap=True)
            self._streaming = True
            self._streamed_text = True
            return
        if isinstance(item, view.MessageItem):
            if self._streaming:
                self._console.print()
                self._streaming = False
            if not self._streamed_text:
                # 没有流式正文（如历史回放）：拿最终块补一次 markdown。
                self._console.print(cards.render_item(item))
            return
        if isinstance(item, view.ApprovalItem):
            await self._ask_approval(item)
            return
        if isinstance(item, view.AskItem):
            await self._answer_question(item)
            return
        if isinstance(item, view.TurnStartedItem):
            self._streamed_text = False
            self._busy = True
            self._queue_depth = 0
        self._console.print(self._safe_render(item))
        if isinstance(item, view.TurnDoneItem):
            self._busy = False
            self._pending_turns = max(0, self._pending_turns - 1)
            if item.usage is not None:
                self._usage = item.usage
            self._console.print()
            self._console.print(self._footer())
            self.done.set()

    def _safe_render(self, item: view.Item) -> Any:
        """单帧渲染不得杀死消费循环：异常降级成一行可见提示，继续消费。"""

        try:
            return cards.render_item(item)
        except Exception as exc:  # noqa: BLE001 - 渲染层绝不能拖垮事件消费
            return strings.render_failed(item.__class__.__name__, str(exc))

    def _footer(self) -> Any:
        """状态栏：形态/忙闲/队列是真值，缺数字段显式渲染 `—`。"""

        return footer.render(
            footer.FooterVM(
                profile=self._profile_name,
                busy=self._busy,
                queue_depth=self._queue_depth,
                context_used=None if self._usage is None else self._usage.context_used,
                context_window=None if self._usage is None else self._usage.context_window,
                cost_usd=None if self._usage is None else self._usage.cost_usd,
            )
        )

    async def _ask_approval(self, item: view.ApprovalItem) -> None:
        """审批：y 通过，其余拒绝（fail-closed 由服务端兜底）。编辑类先给 diff 卡。"""
        self._console.print(cards.render_item(item))
        self._console.print(limits.deadline_hint(self._prompt_timeout()), style=theme.DIM)
        answer = await self._read_answer("  [y/N] 允许执行? ", kind="审批")
        if answer is None:
            self._console.print(strings.APPROVAL_TIMEOUT, style=theme.WARN)
        decision = "approve" if (answer or "").strip().lower() in {"y", "yes"} else "deny"
        await self._host.transport.request(
            "POST",
            f"{PREFIX}/approve",
            body=json.dumps({"id": item.prompt_id, "decision": decision}).encode(),
        )

    async def _answer_question(self, item: view.AskItem) -> None:
        """工具提问：空输入即视为未回答；客户端与同一个超时对齐。"""
        self._console.print(cards.render_item(item))
        self._console.print(
            limits.deadline_hint(self._prompt_timeout(), kind="提问"), style=theme.DIM
        )
        answer = await self._read_answer("  → ", kind="提问")
        if answer is None:
            self._console.print(strings.ASK_TIMEOUT, style=theme.WARN)
        await self._host.transport.request(
            "POST",
            f"{PREFIX}/ask",
            body=json.dumps({"id": item.prompt_id, "answer": answer or ""}).encode(),
        )

    def _prompt_timeout(self) -> float:
        """服务端的提示超时（authority 默认 300s）；拿不到就用契约默认值。"""

        return float(
            getattr(self._host.authority, "prompt_timeout", limits.DEFAULT_TIMEOUT_SECONDS)
        )

    async def _read_answer(
        self, prompt: str, *, kind: str = "审批"
    ) -> str | None:
        """读一个回答；超时返回 None，让调用方按 fail-closed 结算。

        TTY 上走带倒计时工具条的 PromptSession（每秒刷新剩余秒数，plan03 波 B）；
        非 TTY 回退裸 `input`，超时语义不变。
        """

        timeout = self._prompt_timeout()
        session = limits.build_session(timeout, kind=kind)
        try:
            if session is None:
                return await asyncio.wait_for(
                    asyncio.to_thread(input, prompt), timeout=timeout
                )
            return await asyncio.wait_for(
                asyncio.to_thread(session.prompt, prompt),  # type: ignore[attr-defined] # 可选依赖的会话对象
                timeout=timeout,
            )
        except TimeoutError:
            return None
