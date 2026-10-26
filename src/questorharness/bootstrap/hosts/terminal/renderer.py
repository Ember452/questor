"""终端渲染器：wire 帧 → 视图模型 → 图元，并把审批/提问回灌成 HTTP 调用。

属于呈现层：只消费 serve 契约，不持有会话事实（plan03 §2.1 不变量）。

两种输入归属（plan03 §2.4 的"审批/提问时序"）：
- `loop`  ：REPL 在读下一行 → 审批/提问变成**主输入的一个模态**，答案从同一个
  PromptSession 读。这是唯一不会出现两个 Application 抢 tty 的形态，也是
  `prompt_toolkit` 在工作线程里 `asyncio.run()` 造出"Executor shutdown"堆栈的根治。
- `inline`：单次 prompt（`-p`）没有人替它读行 → 保持原来的就地阻塞询问。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from rich.console import Console
from rich.text import Text

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


@dataclass
class PendingPrompt:
    """等回答的模态：审批或提问。`loop` 模式下由主输入循环代答。"""

    kind: str  # "approval" | "ask"
    prompt_id: str
    options: tuple[str, ...] = ()


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
        self._pending: PendingPrompt | None = None
        # 缺省 inline：单次 prompt / 测试里的裸渲染器没人替它读行，就地询问才安全。
        # REPL 由 `run_terminal_client` 显式切到 loop（审批变主输入的模态）。
        self._mode = "inline"
        # 状态栏四字段真值（模型/推理强度/权限模式/分支），来自 catalog，缺省渲染 —。
        self._model: str | None = None
        self._effort: str | None = None
        self._permission_mode: str | None = None
        self._branch: str | None = None
        self.done = asyncio.Event()

    # ---- 对外状态 -------------------------------------------------------
    @property
    def busy(self) -> bool:
        """当前是否有回合在跑（决定 Ctrl-C 是取消还是清行）。"""

        return self._busy

    @property
    def pending_turns(self) -> int:
        """已提交但未收到 turn_done 的回合数（退出前要收干净）。"""

        return self._pending_turns

    @property
    def has_pending_prompt(self) -> bool:
        """有审批/提问在等回答（主循环据此把下一行当答案，而不是新消息）。"""

        return self._pending is not None

    def set_mode(self, mode: str) -> None:
        """`loop` = 主循环代答；`inline` = 渲染器就地询问（单次 prompt）。"""

        self._mode = mode

    def expect_turn(self) -> None:
        """记一个已受理的提交；turn_done 时清除。"""

        self._pending_turns += 1

    def note_queued(self) -> None:
        """服务端排上了：立即给一行可见回执，用户才知道没丢。"""

        self._queue_depth = 1
        self._console.print(strings.QUEUED, style=theme.DIM)
        if self._mode != "loop":
            self._console.print(self._footer())

    def note_cancel_requested(self) -> None:
        """已发 /cancel：回合结不结束由服务端决定，但用户要知道请求已送达。"""

        self._console.print(strings.CANCEL_SENT, style=theme.WARN)

    def show(self, text: str) -> None:
        """终端本地提示（面板清单/空态/取数据失败）。"""

        self._console.print(text, style=theme.DIM)

    def footer_vm(self) -> footer.FooterVM:
        """状态栏视图模型（工具栏与回退打印共用一份真值）。"""

        return footer.FooterVM(
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

    # ---- 事件消费 -------------------------------------------------------
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
            # 流式正文原样输出：交给终端自己折行。不在这里重排 markdown——
            # 任何"按块重画"在中文段落上都会变成一字一行（rich 按 cell 断）。
            # 必须用 Text 包裹：裸 str 会被当 rich markup 解析，`[index]` 会被吃掉。
            self._console.print(Text(item.text), end="", soft_wrap=True)
            self._streaming = True
            self._streamed_text = True
            return
        if isinstance(item, view.MessageItem):
            self._finish_stream()
            if item.usage is not None:
                # usage 只随 message 帧到达（turn_done 不带），状态栏的 ctx/$ 靠这里取值。
                self._usage = item.usage
            if not self._streamed_text:
                # 没有流式正文（历史回放 / 无 delta 的回合）：拿最终块补一次 markdown。
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
            self._console.print(Text(strings.THINKING, style=theme.DIM))
            return
        if isinstance(item, view.TurnDoneItem):
            self._finish_stream()
            self._busy = False
            self._pending = None  # 上一回合的模态一并作废
            self._pending_turns = max(0, self._pending_turns - 1)
            try:
                self._console.print(self._safe_render(item))
                if item.usage is not None:
                    self._usage = item.usage
                # 回合可能换过模型/权限档（/model、/permissions）：重拉一次状态栏真值。
                await self.refresh_status()
                if self._mode != "loop":
                    self._console.print()
                    self._console.print(self._footer())
            finally:
                # 无论打印是否成功（写端仍可能抛编码错）：`done` 必须置位，
                # 否则 EOF 前的 drain 会白等到超时（实跑现场：白等 300s）。
                self.done.set()
            return
        self._console.print(self._safe_render(item))

    def _finish_stream(self) -> None:
        """收尾流式正文：只补一个换行，不动已经写出去的字符。"""

        if self._streaming:
            self._console.print()
            self._streaming = False

    def _safe_render(self, item: view.Item) -> Any:
        """单帧渲染不得杀死消费循环：异常降级成一行可见提示，继续消费。"""

        try:
            return cards.render_item(item)
        except Exception as exc:  # noqa: BLE001 - 渲染层绝不能拖垮事件消费
            return strings.render_failed(item.__class__.__name__, str(exc))

    def _footer(self) -> Any:
        """回退路径的状态栏（一行，按列宽截断）。"""

        return footer.render(self.footer_vm(), self._console.width)

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

    # ---- 审批 / 提问 -----------------------------------------------------
    async def _ask_approval(self, item: view.ApprovalItem) -> None:
        """审批：y 通过，其余拒绝（fail-closed 由服务端兜底）。编辑类先给 diff 卡。"""

        self._finish_stream()
        self._console.print(cards.render_item(item))
        self._console.print(limits.deadline_hint(self._prompt_timeout()), style=theme.DIM)
        if self._mode == "loop":
            # 主输入循环代答：不另起 PromptSession（那会两个 Application 抢 tty，
            # 并在 Windows 上刷 "Executor shutdown has been called"）。
            self._pending = PendingPrompt("approval", item.prompt_id)
            return
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
        await self._post_decision("approve", item.prompt_id, decision)

    async def _answer_question(self, item: view.AskItem) -> None:
        """工具提问：空输入即视为未回答；客户端与同一个超时对齐。"""

        self._finish_stream()
        self._console.print(cards.render_item(item))
        self._console.print(
            limits.deadline_hint(self._prompt_timeout(), kind="提问"), style=theme.DIM
        )
        if self._mode == "loop":
            self._pending = PendingPrompt("ask", item.prompt_id, item.options)
            return
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
        await self._post_decision("ask", item.prompt_id, resolve_answer(answer, item.options))

    async def answer_pending(self, line: str) -> bool:
        """把主循环读到的一行当成本回合的审批/提问答案；无效回答返回 False。"""

        pending = self._pending
        if pending is None:
            return True
        raw = line.strip()
        if pending.kind == "approval":
            lowered = raw.lower()
            if lowered in {"y", "yes"}:
                await self._post_decision("approve", pending.prompt_id, "approve")
            elif lowered in {"n", "no", ""}:
                await self._post_decision("approve", pending.prompt_id, "deny")
            else:
                self._console.print(strings.APPROVAL_UNKNOWN, style=theme.WARN)
                return False
        else:
            await self._post_decision("ask", pending.prompt_id, resolve_answer(raw, pending.options))
        self._pending = None
        return True

    async def _post_decision(self, endpoint: str, prompt_id: str, value: str) -> None:
        """把裁决回灌给 serve（`/approve` 或 `/ask`）。"""

        body = (
            {"id": prompt_id, "decision": value}
            if endpoint == "approve"
            else {"id": prompt_id, "answer": value}
        )
        await self._host.transport.request(
            "POST", f"{PREFIX}/{endpoint}", body=json.dumps(body).encode()
        )

    def _prompt_timeout(self) -> float:
        """服务端的提示超时（authority 默认 300s）；拿不到就用契约默认值。"""

        return float(
            getattr(self._host.authority, "prompt_timeout", limits.DEFAULT_TIMEOUT_SECONDS)
        )

    async def _read_answer(self, prompt: str, *, kind: str = "审批") -> str | None:
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
                session.prompt_async(prompt),  # type: ignore[attr-defined] # 可选依赖的会话对象
                timeout=timeout,
            )
        except TimeoutError:
            return None
