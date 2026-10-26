"""Textual 全屏 TUI：对话区 + 带框输入 + `/` 候选 + 状态栏 + 审批模态。

形态照 OpenHarness `ui/textual_app.py`：App + VerticalScroll + Input + Footer +
ModalScreen。事件源仍是本仓 serve 的 SSE 帧，所以引擎与协议一行不改。

为什么必须换成这个（而不是继续 prompt_toolkit 行式 prompt）：
- 行式 prompt 只能在"一行提示符"上打补丁：输入框没法画框、状态栏没法固定、
  `/` 候选只能靠浮动菜单（Windows 控制台上经常不出现）；
- Textual 自己拥有屏幕，以上三件事都是普通控件，且流式文本可以**原地重排**
  （scrollback 模型做不到：写出去的字不能再改）。
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
from typing import Any

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, Markdown, Static

from questorharness.bootstrap.hosts.serve import terminal_theme as theme
from questorharness.bootstrap.hosts.serve.host import ServeHost
from questorharness.bootstrap.hosts.terminal import cards, diff as diff_card, footer, strings, width
from questorharness.bootstrap.hosts.terminal import wire_view as view

PREFIX = "/rt/r1"

#: 流式正文的重排节流：Textual 的 Markdown 每次 update 都是全量重渲染。
STREAM_REFRESH_SECONDS = 0.08
#: 候选清单最多显示多少行（再多就把输入区挤没了）。
HINT_ROWS = 8


class ApprovalScreen(ModalScreen[str]):
    """审批模态：y 允许 / n 拒绝（回车默认拒绝，与服务端 fail-closed 一致）。

    只放“要你决定的那一行”：工具名 + 目标（截断）+ diff。
    说明文字、档位提示、选项说明**不在这里重复**——按钮就是选项，
    档位提示属于 `:mode`，塞进模态只会把框撑成整屏（实跑反馈“太大了”）。
    """

    BINDINGS = [
        Binding("y", "choose('y')", "允许"),
        Binding("n", "choose('n')", "拒绝"),
        Binding("escape", "choose('n')", "拒绝"),
    ]

    def __init__(self, item: view.ApprovalItem) -> None:
        super().__init__()
        self._item = item

    def compose(self) -> ComposeResult:
        item = self._item
        body: list[Any] = [Static(approval_head(item))]
        if item.patch:
            body.append(
                Static(
                    diff_card.render_patch(
                        item.patch, added=item.added or 0, removed=item.removed or 0
                    )
                )
            )
        elif item.detail:
            body.append(Static(diff_card.render_detail(item.detail)))
        yield Container(
            *body,
            Horizontal(
                Button("允许 y", id="y", variant="success"),
                Button("拒绝 n", id="n", variant="error"),
                classes="approval-actions",
            ),
            id="approval-box",
        )

    @on(Button.Pressed)
    def _pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id or "n")

    def action_choose(self, value: str) -> None:
        self.dismiss(value)


class QuestorApp(App[None]):
    """终端产品本体：一个屏幕内完成对话、工具、审批、指令。"""

    CSS = """
    Screen { layout: vertical; }
    #conversation { height: 1fr; padding: 0 1; }
    #hints {
        height: auto;
        max-height: 10;
        padding: 0 1;
        color: $text-muted;
    }
    #prompt-box {
        height: 3;
        margin: 0 1;
        border: round $primary;
        padding: 0 1;
    }
    #prompt { border: none; background: transparent; }
    #status { height: 1; padding: 0 1; color: $text-muted; }
    #approval-box {
        width: 76;
        max-width: 96%;
        height: auto;
        max-height: 70%;
        border: round $warning;
        padding: 0 1;
        background: $surface;
        align: center middle;
    }
    .approval-actions { height: auto; padding: 1 0 0 0; align: center middle; }
    .approval-actions Button { width: 14; min-width: 14; height: 3; }
    /* 会话区里每条消息之间的呼吸 */
    .turn-rule { color: $text-muted; }
    """

    BINDINGS = [
        Binding("ctrl+c", "interrupt", "中止回合"),
        Binding("ctrl+d", "quit_app", "退出"),
        Binding("ctrl+l", "clear_screen", "清屏"),
    ]

    def __init__(self, host: ServeHost, *, profile_name: str = "?") -> None:
        super().__init__()
        self._host = host
        self._profile_name = profile_name
        self._commands: dict[str, str] = {}
        self._busy = False
        self._pending: view.ApprovalItem | None = None
        self._stream_buffer = ""
        self._stream_view: Markdown | None = None
        self._stream_dirty = False
        self._status: footer.FooterVM = footer.FooterVM(profile=profile_name)

    # ---- 组装 -----------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="conversation")
        yield Static("", id="hints")
        with Container(id="prompt-box"):
            yield Input(placeholder="说一句话开始 · / 看指令 · Ctrl-C 中止", id="prompt")
        yield Static("", id="status")
        yield Footer()

    async def on_mount(self) -> None:
        self.query_one("#prompt", Input).focus()
        self.set_interval(STREAM_REFRESH_SECONDS, self._flush_stream)
        await self._load_commands()
        self._write(cards.banner())
        self._write(Text(f"{self._profile_name} · {strings.BRAND_TAGLINE}", style=theme.DIM))
        self._write(Text(strings.EMPTY_STATE_LINES[0], style=theme.DIM))
        self._write(Text(strings.EMPTY_STATE_LINES[1], style=theme.DIM))
        self._render_status()
        await self._refresh_status()
        self.run_worker(self._consume_events(), exclusive=False, name="sse")

    async def _load_commands(self) -> None:
        from questorharness.bootstrap.hosts.terminal.app import (
            completion_catalog,
            fetch_commands,
        )

        self._commands = completion_catalog(await fetch_commands(self._host))

    # ---- 写屏 -----------------------------------------------------------
    def _conversation(self) -> VerticalScroll:
        return self.query_one("#conversation", VerticalScroll)

    def _write(self, renderable: Any) -> None:
        """追加一块"写完就不动"的内容（卡片、提示、回合小结）。"""

        self._end_stream()
        self._conversation().mount(Static(renderable))

    def _begin_stream(self) -> None:
        if self._stream_view is None:
            self._stream_view = Markdown("")
            self._conversation().mount(self._stream_view)
            self._stream_buffer = ""

    def _feed_stream(self, delta: str) -> None:
        self._begin_stream()
        self._stream_buffer += delta
        self._stream_dirty = True

    def _flush_stream(self) -> None:
        """把缓冲的增量交给 Markdown 重排（节流；中文/代码块都能正确折行）。"""

        if not self._stream_dirty or self._stream_view is None:
            return
        self._stream_dirty = False
        self._stream_view.update(self._stream_buffer)
        self._conversation().scroll_end(animate=False)

    def _end_stream(self) -> None:
        self._flush_stream()
        self._stream_view = None
        self._stream_buffer = ""

    # ---- 状态栏 ---------------------------------------------------------
    def _render_status(self) -> None:
        columns = max(20, (self.size.width or 80) - 2)
        self.query_one("#status", Static).update(
            Text(footer.toolbar_text(self._status, columns), style=theme.DIM)
        )

    async def _refresh_status(self) -> None:
        async def _items(kind: str) -> list[dict[str, Any]]:
            response = await self._host.transport.request("GET", f"{PREFIX}/catalog/{kind}")
            if response.status >= 400:
                return []
            return list(json.loads(response.body).get("items", []))

        status = self._status
        for kind in ("posture", "status", "git"):
            try:
                items = await _items(kind)
            except Exception:  # noqa: BLE001 - 状态栏缺数据不阻断回合
                continue
            if kind == "posture":
                current = next((i for i in items if i.get("current")), None)
                if current:
                    status = dataclasses.replace(status, permission_mode=str(current.get("id")))
            elif kind == "status":
                labels = {str(i.get("id")): str(i.get("label", "")) for i in items}
                status = dataclasses.replace(
                    status,
                    model=labels.get("model") or status.model,
                    effort=labels.get("effort") or status.effort,
                )
            elif items:
                status = dataclasses.replace(status, branch=str(items[0].get("id")))
        self._status = status
        self._render_status()

    # ---- 事件流 ---------------------------------------------------------
    async def _consume_events(self) -> None:
        response = await self._host.transport.request("GET", f"{PREFIX}/events")
        stream = response.stream
        if stream is None:
            return
        buffer = b""
        async for chunk in stream:
            buffer += chunk
            while b"\n\n" in buffer:
                block, buffer = buffer.split(b"\n\n", 1)
                if not block.startswith(b"id:"):
                    continue
                frame = _frame(block)
                if frame is None:
                    continue
                try:
                    self._render_frame(frame)
                except Exception as exc:  # noqa: BLE001 - 单帧异常不得杀死 TUI
                    self._write(
                        Text(
                            strings.render_failed(str(frame.get("kind")), str(exc)),
                            style=theme.ERR,
                        )
                    )

    def _render_frame(self, frame: dict[str, Any]) -> None:
        item = view.view_of(frame)
        if isinstance(item, view.TextItem):
            self._feed_stream(item.text)
            return
        if isinstance(item, view.MessageItem):
            self._end_stream()
            if item.usage is not None:
                self._status = dataclasses.replace(
                    self._status,
                    context_used=item.usage.context_used,
                    context_window=item.usage.context_window,
                    cost_usd=item.usage.cost_usd,
                )
                self._render_status()
            return
        if isinstance(item, view.TurnStartedItem):
            self._busy = True
            self._status = dataclasses.replace(self._status, busy=True)
            self._render_status()
            self._write(Text(strings.THINKING, style=theme.DIM))
            return
        if isinstance(item, view.TurnDoneItem):
            self._end_stream()
            self._busy = False
            self._pending = None
            self._status = dataclasses.replace(self._status, busy=False)
            self._render_status()
            self.run_worker(self._refresh_status(), exclusive=False)
            self._write(cards.render_item(item))
            return
        if isinstance(item, view.ApprovalItem):
            self._ask(item)
            return
        self._write(cards.render_item(item))

    def _ask(self, item: view.ApprovalItem) -> None:
        self._pending = item
        self.push_screen(ApprovalScreen(item), self._on_approval)

    def _on_approval(self, answer: str | None) -> None:
        item, self._pending = self._pending, None
        if item is None:
            return
        decision = "approve" if answer == "y" else "deny"
        self.run_worker(self._post("approve", {"id": item.prompt_id, "decision": decision}))

    async def _post(self, endpoint: str, body: dict[str, Any]) -> None:
        await self._host.transport.request(
            "POST", f"{PREFIX}/{endpoint}", body=json.dumps(body).encode()
        )

    # ---- 输入 -----------------------------------------------------------
    @on(Input.Changed, "#prompt")
    def _show_hints(self, event: Input.Changed) -> None:
        """打 `/` 立刻在输入框上方给出候选——不依赖任何浮动菜单。"""

        hints = self.query_one("#hints", Static)
        text = event.value
        if not text.startswith("/") or " " in text:
            hints.update("")
            return
        matches = [(name, desc) for name, desc in self._commands.items() if name.startswith(text)]
        if not matches:
            matches = [
                (name, desc)
                for name, desc in self._commands.items()
                if text.lstrip("/") and text.lstrip("/") in name
            ]
        if not matches:
            hints.update(Text(strings.NO_MATCH_HINT, style=theme.WARN))
            return
        lines = [f"{name:<24}{desc}" for name, desc in matches[:HINT_ROWS]]
        hints.update(Text("\n".join(lines), style=theme.DIM))

    @on(Input.Submitted, "#prompt")
    async def _submit(self, event: Input.Submitted) -> None:
        line = event.value.strip()
        event.input.value = ""
        if not line:
            return
        if self._busy:
            self._write(Text(strings.BUSY_REFUSED, style=theme.WARN))
            return
        unknown = line.split(maxsplit=1)[0]
        if line.startswith("/") and unknown not in self._commands:
            self._write(Text(strings.UNKNOWN_COMMAND.format(name=unknown), style=theme.WARN))
            return
        self._write(Text(f"❯ {line}", style=theme.BOLD))
        self._busy = True
        response = await self._host.transport.request(
            "POST",
            f"{PREFIX}/submit",
            body=json.dumps({"line": line, "clientRequestId": _request_id()}).encode(),
        )
        if response.status >= 400:
            self._busy = False
            payload = json.loads(response.body)
            self._write(
                Text(
                    strings.SUBMIT_REFUSED.format(
                        detail=f"{payload.get('code')}: {payload.get('message')}"
                    ),
                    style=theme.ERROR,
                )
            )

    # ---- 动作 -----------------------------------------------------------
    def action_interrupt(self) -> None:
        if not self._busy:
            return
        self.run_worker(self._post("cancel", {}))
        self._write(Text(strings.CANCEL_SENT, style=theme.WARN))

    def action_quit_app(self) -> None:
        self.exit()

    def action_clear_screen(self) -> None:
        self._conversation().remove_children()
        self._stream_view = None
        self._stream_buffer = ""


def approval_head(item: view.ApprovalItem) -> Text:
    """审批模态的标题行：工具名 + 目标（压成一行、截断）。

    只占一行是硬约束：目标（subject）在 default 模式下是一整段英文说明，
    原样塞进模态会把框撑成整屏（实跑截图）。
    """

    head = Text()
    head.append("⚠ 需要审批  ", style=theme.ACCENT)
    head.append(item.tool, style=theme.BOLD)
    target = _one_line(item.subject)
    if target:
        head.append("  " + width.truncate(target, 72), style=theme.NET)
    return head


def _one_line(text: str) -> str:
    """压成一行（审批目标通常是长句，多行会把模态撑高）。"""

    return " ".join(text.split())


def _frame(block: bytes) -> dict[str, Any] | None:
    for line in block.splitlines():
        if line.startswith(b"data: "):
            try:
                parsed = json.loads(line[len(b"data: ") :])
            except json.JSONDecodeError:
                return None
            return parsed if isinstance(parsed, dict) else None
    return None


def _request_id() -> str:
    return os.urandom(8).hex()


async def run_tui(host: ServeHost) -> int:
    """跑全屏 TUI 直到用户退出；宿主生命周期由调用方管理。"""

    from questorharness.bootstrap.hosts.terminal.app import profile_info

    name, _description = await profile_info(host)
    app = QuestorApp(host, profile_name=name)
    await app.run_async()
    return 0
