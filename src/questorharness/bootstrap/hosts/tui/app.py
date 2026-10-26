"""Textual 全屏 TUI：对话区 + 带框输入 + `/` 候选 + `:` 面板 + 状态栏 + 审批。

形态照 OpenHarness `ui/textual_app.py`：App + VerticalScroll + Input + Footer +
ModalScreen。事件源仍是本仓 serve 的 SSE 帧，所以引擎与协议一行不改。

分层（每个文件一个职责，避免又长成 god file）：
- `app.py`     ：装配、提交、流式、状态栏、事件消费
- `panels.py`  ：`:` 面板（列表 + 搜索 + 选中回命令）
- `approval.py`：审批模态
- `replay.py`  ：`--resume` 的历史回放（纯函数）
"""

from __future__ import annotations

import dataclasses
import json
import os
from typing import Any, ClassVar

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, VerticalScroll
from textual.widgets import Footer, Input, Markdown, Static

from questorharness.bootstrap.hosts.serve import terminal_theme as theme
from questorharness.bootstrap.hosts.serve.host import ServeHost
from questorharness.bootstrap.hosts.terminal import cards, footer, pickers, strings
from questorharness.bootstrap.hosts.terminal import wire_view as view
from questorharness.bootstrap.hosts.tui.approval import ApprovalScreen, approval_head
from questorharness.bootstrap.hosts.tui.panels import PanelScreen
from questorharness.bootstrap.hosts.tui.replay import history_renderables

PREFIX = "/rt/r1"

#: 流式正文的重排节流：Textual 的 Markdown 每次 update 都是全量重渲染。
STREAM_REFRESH_SECONDS = 0.08
#: 候选清单最多显示多少行（再多就把输入区挤没了）。
HINT_ROWS = 8

__all__ = ["QuestorApp", "approval_head", "run_tui"]


class QuestorApp(App[None]):
    """终端产品本体：一个屏幕内完成对话、工具、审批、指令与面板。"""

    CSS: ClassVar[str] = """
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
    /* 审批模态：固定窄宽，长说明压成一行，见 approval.py */
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
    /* `:` 面板 */
    #panel-box {
        width: 90;
        max-width: 96%;
        height: auto;
        max-height: 80%;
        border: round $primary;
        padding: 0 1;
        background: $surface;
        align: center middle;
    }
    #panel-list { height: auto; max-height: 20; }
    .turn-rule { color: $text-muted; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+c", "interrupt", "中止回合"),
        Binding("ctrl+d", "quit_app", "退出"),
        Binding("ctrl+l", "clear_screen", "清屏"),
    ]

    def __init__(self, host: ServeHost, *, profile_name: str = "?", replay: bool = False) -> None:
        super().__init__()
        self._host = host
        self._profile_name = profile_name
        self._replay = replay
        self._commands: dict[str, str] = {}
        self._busy = False
        self._pending: view.ApprovalItem | None = None
        self._pending_panel: pickers.Panel | None = None
        self._stream_buffer = ""
        self._stream_view: Markdown | None = None
        self._stream_dirty = False
        self._status: footer.FooterVM = footer.FooterVM(profile=profile_name)

    # ---- 组装 -----------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="conversation")
        yield Static("", id="hints")
        with Container(id="prompt-box"):
            yield Input(
                placeholder="说一句话 · / 指令 · : 面板 · Ctrl-C 中止",
                id="prompt",
            )
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
        if self._replay:
            await self._replay_history()
        self.run_worker(self._consume_events(), exclusive=False, name="sse")

    async def _load_commands(self) -> None:
        from questorharness.bootstrap.hosts.terminal.app import (
            completion_catalog,
            fetch_commands,
        )

        self._commands = completion_catalog(await fetch_commands(self._host))

    async def _replay_history(self) -> None:
        """`--resume`：把上次会话的文本回放进对话区（失败不阻断）。"""

        try:
            response = await self._host.transport.request("GET", f"{PREFIX}/history")
            payload = json.loads(response.body)
        except Exception:  # noqa: BLE001 - 回放是增强，读不到就当新会话
            return
        rows = history_renderables(list(payload.get("messages", [])))
        if not rows:
            return
        self._write(Text(strings.REPLAY_LEAD.format(shown=len(rows)), style=theme.DIM))
        for row in rows:
            self._write(row)

    # ---- 写屏 -----------------------------------------------------------
    def _conversation(self) -> VerticalScroll:
        return self.query_one("#conversation", VerticalScroll)

    def _write(self, renderable: Any) -> None:
        """追加一块"写完就不动"的内容（卡片、提示、回合小结）。"""

        self._end_stream()
        self._conversation().mount(Static(renderable))
        self._conversation().scroll_end(animate=False)

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
        if text.startswith(":"):
            hints.update(Text(pickers.list_hint(), style=theme.DIM))
            return
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
        await self._dispatch(line)

    async def _dispatch(self, line: str) -> None:
        """一行输入的统一入口（输入框与面板选中都走这里）。"""

        if not line:
            return
        if self._busy:
            self._write(Text(strings.BUSY_REFUSED, style=theme.WARN))
            return
        if line.startswith(":"):
            # 面板是模态：选中结果走回调（`wait_for_dismiss` 只能在 worker 里用，
            # 而输入事件本身不在 worker 上）。
            await self._open_panel(line)
            return
        head = line.split(maxsplit=1)[0]
        if line.startswith("/") and head not in self._commands:
            self._write(Text(strings.UNKNOWN_COMMAND.format(name=head), style=theme.WARN))
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
                    style=theme.ERR,
                )
            )

    async def _open_panel(self, line: str) -> None:
        """`:` 面板：取数（与行式 REPL 同源）→ 打开选择器，选中后走回调。"""

        from questorharness.bootstrap.hosts.terminal.app import panel_items

        panel = pickers.resolve(line)
        if panel is None:
            self._write(Text(pickers.list_hint(), style=theme.DIM))
            return
        try:
            items = await panel_items(self._host, panel)
        except Exception as exc:  # noqa: BLE001 - 取数失败不得影响会话
            self._write(Text(strings.PANEL_UNAVAILABLE.format(reason=exc), style=theme.WARN))
            return
        if not items:
            self._write(Text(strings.PANEL_EMPTY, style=theme.DIM))
            return
        self._pending_panel = panel
        self.push_screen(PanelScreen(panel, items), self._on_panel_choice)

    def _on_panel_choice(self, chosen: str | None) -> None:
        """面板选定：拼成命令再走同一条提交链。"""

        panel, self._pending_panel = self._pending_panel, None
        if panel is None or not isinstance(chosen, str):
            return
        action = pickers.action_line(panel, chosen)
        if action:
            self.run_worker(self._dispatch(action), exclusive=False)

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


async def run_tui(host: ServeHost, *, replay: bool = False) -> int:
    """跑全屏 TUI 直到用户退出；宿主生命周期由调用方管理。"""

    from questorharness.bootstrap.hosts.terminal.app import profile_info

    name, _description = await profile_info(host)
    app = QuestorApp(host, profile_name=name, replay=replay)
    await app.run_async()
    return 0
