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


def _current_id(items: list[dict[str, Any]]) -> str | None:
    """带 current 标记的行 id（没有标记行 → None）。"""

    for item in items:
        if item.get("current"):
            return str(item.get("id", ""))
    return None


def resolve_answer(raw: str | None, options: tuple[str, ...]) -> str:
    """把用户的回答归一成回传值（plan03 A2）。

    - None/空 → 空串（服务端按“未回答”处理）；
    - 给了选项且输入是序号 → 映射回选项原文（越界不猜，原样回传）；
    - 其余一律原样回传（允许自由文本覆盖选项）。
    """

    if raw is None:
        return ""
    text = raw.strip()
    if not text:
        return ""
    if options and text.isdigit():
        index = int(text) - 1
        if 0 <= index < len(options):
            return options[index]
    return text


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
        # 状态栏四字段真值（模型/推理强度/权限模式/分支），来自 catalog，缺省渲染 —。
        self._model: str | None = None
        self._effort: str | None = None
        self._permission_mode: str | None = None
        self._branch: str | None = None
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
                    try:
                        await self._render(frame)
                    except Exception as exc:  # noqa: BLE001 - 单帧任何异常不得杀死消费链
                        # 不能回 `console.print`：rich 会把上一行没写出去的字节再拼进来，
                        # 坏控制台依旧抛。直写一眼纯文本，失败也只丢这一行。
                        try:
                            self._console.file.write(
                                strings.render_failed(
                                    item=str(frame.get("kind", "?")), detail=type(exc).__name__
                                )
                                + "\n"
                            )
                            self._console.file.flush()
                        except Exception:  # noqa: BLE001 - 降级也要尽力而为
                            pass
                        if frame.get("kind") == "turn_done":
                            self.done.set()
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
        if isinstance(item, view.TurnDoneItem):
            self._busy = False
            self._pending_turns = max(0, self._pending_turns - 1)
            try:
                self._console.print(self._safe_render(item))
                if item.usage is not None:
                    self._usage = item.usage
                # 回合可能换过模型/权限档（/model、/permissions）：重拉一次状态栏真值。
                await self.refresh_status()
                self._console.print()
                self._console.print(self._footer())
            finally:
                # 无论打印是否成功（写端仍可能抛编码错）：`done` 必须置位，
                # 否则 EOF 前的 drain 会白等到超时（实跑现场：白等 300s）。
                self.done.set()
            return
        self._console.print(self._safe_render(item))

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
                model=self._model,
                effort=self._effort,
                permission_mode=self._permission_mode,
                branch=self._branch,
                busy=self._busy,
                queue_depth=self._queue_depth,
                context_used=None if self._usage is None else self._usage.context_used,
                context_window=None if self._usage is None else self._usage.context_window,
                cost_usd=None if self._usage is None else self._usage.cost_usd,
            )
        )

    async def refresh_status(self) -> None:
        """从 catalog 拉状态栏四字段真值（posture / status / git）。

        fail-soft：任何一步失败都保留上次已知值——状态栏是增强信息，
        不得让它拖垮 REPL。
        """

        async def _items(kind: str) -> list[dict[str, Any]]:
            response = await self._host.transport.request("GET", f"{PREFIX}/catalog/{kind}")
            if response.status >= 400:
                return []
            return list(json.loads(response.body).get("items", []))

        for kind in ("posture", "status", "git"):
            try:
                items = await _items(kind)
            except Exception:  # noqa: BLE001 - 状态栏缺数据不阻断回合
                continue
            if kind == "posture":
                self._permission_mode = _current_id(items) or self._permission_mode
            elif kind == "status":
                labels = {str(item.get("id")): str(item.get("label", "")) for item in items}
                self._model = labels.get("model") or self._model
                self._effort = labels.get("effort") or self._effort
            else:
                self._branch = (items[0].get("id") if items else None) or self._branch

    async def _ask_approval(self, item: view.ApprovalItem) -> None:
        """审批：y 通过，其余拒绝（fail-closed 由服务端兜底）。编辑类先给 diff 卡。"""
        self._console.print(cards.render_item(item))
        self._console.print(limits.deadline_hint(self._prompt_timeout()), style=theme.DIM)
        notice = ""
        try:
            answer = await self._read_answer("  [y/N] 允许执行? ", kind="审批")
        except KeyboardInterrupt:
            # Ctrl-C 四语义表：审批中 = deny；异常击穿 REPL 才是错的。
            answer, notice = None, strings.APPROVAL_INTERRUPT
        else:
            notice = strings.APPROVAL_TIMEOUT if answer is None else ""
        if notice:
            self._console.print(notice, style=theme.WARN)
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
        notice = ""
        try:
            answer = await self._read_answer("  → ", kind="提问")
        except KeyboardInterrupt:
            # Ctrl-C 四语义表：提问中 = 未回答，不得击穿 REPL。
            answer, notice = None, strings.ASK_INTERRUPT
        else:
            notice = strings.ASK_TIMEOUT if answer is None else ""
        if notice:
            self._console.print(notice, style=theme.WARN)
        payload = resolve_answer(answer, item.options)
        await self._host.transport.request(
            "POST",
            f"{PREFIX}/ask",
            body=json.dumps({"id": item.prompt_id, "answer": payload}).encode(),
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
