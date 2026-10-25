"""REPL 装配与会话循环：唯一写终端通道、单次/交互两种模式、面板入口。

这一层只做"读一行 → 提交 → 收帧渲染"的调度；渲染在 `renderer`，视图模型在
`wire_view`，图元在 `cards`，输入在 `input_session`，键位在 `keymap`。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import Console

from questorharness.bootstrap.hosts.serve import terminal_theme as theme
from questorharness.bootstrap.hosts.serve.host import ServeHost
from questorharness.bootstrap.hosts.terminal import cards, paste, pickers, strings
from questorharness.bootstrap.hosts.terminal.renderer import TerminalRenderer

if TYPE_CHECKING:
    from prompt_toolkit import PromptSession

    _PS = PromptSession[Any]

PREFIX = "/rt/r1"
EOF = "__questor_eof__"
INTERRUPT = "__questor_interrupt__"


@dataclass(frozen=True)
class SubmitResult:
    """提交裁决：started / queued / 被拒（turn_id 为 None）。"""

    turn_id: str | None
    state: str


def completion_catalog(commands: list[dict[str, Any]]) -> dict[str, str]:
    """指令目录 → 补全元数据（主名 + 别名 → 描述）。纯函数，供单测。"""
    catalog: dict[str, str] = {}
    for command in commands:
        catalog[f"/{command['name']}"] = str(command.get("description", ""))
        for alias in command.get("aliases", []) or []:
            catalog.setdefault(f"/{alias}", str(command.get("description", "")))
    return catalog


def build_prompt_session(commands: list[dict[str, Any]]) -> "_PS | None":
    """有 prompt_toolkit 且在 TTY 上时建交互会话；否则返回 None（回退裸 input）。"""
    # 惰性导入：输入层与键位都不属包根的冷导入路径（prompt_toolkit 是可选依赖）。
    from questorharness.bootstrap.hosts.terminal import input_session, keymap

    catalog = completion_catalog(commands)
    history_path = Path.home() / ".questorharness" / "terminal_history"
    return input_session.build(
        catalog, history_path=history_path, key_bindings=keymap.build()
    )


def _prompt_once(session: "_PS") -> str:
    """同步读一行：Ctrl-C 交回中断哨兵（回合中会变成 /cancel）。运行在 worker 线程。"""
    while True:
        try:
            text: str = session.prompt("> ")
            return text
        except KeyboardInterrupt:
            return INTERRUPT


async def read_line(session: "_PS | None") -> str:
    """读一行输入；EOF / Ctrl-C 各走一个哨兵。session 为空时回退裸 input。"""
    if session is None:
        try:
            return await asyncio.to_thread(input, "> ")
        except EOFError:
            return EOF
        except KeyboardInterrupt:
            return INTERRUPT
    try:
        return await asyncio.to_thread(_prompt_once, session)
    except EOFError:
        return EOF


async def fetch_commands(host: ServeHost) -> list[dict[str, Any]]:
    """指令目录（补全菜单数据源）；失败回空列表，不阻断 REPL。"""
    try:
        response = await host.transport.request("GET", f"{PREFIX}/commands")
        payload = json.loads(response.body)
        return list(payload.get("commands", []))
    except Exception:  # noqa: BLE001 - 补全是增强体验，缺席可用
        return []


async def print_banner(host: ServeHost, output: Console) -> str:
    """交互模式横幅：Reasonix ASCII art + 形态 + 用法提示；返回形态名供状态栏用。"""
    output.print(cards.banner())
    name = "?"
    try:
        response = await host.transport.request("GET", f"{PREFIX}/profile")
        profile = json.loads(response.body)
        name = str(profile.get("name", "?"))
        output.print(
            f"[bold]{name}[/bold] · {profile.get('description', '')}",
            style=theme.DIM,
        )
    except Exception:  # noqa: BLE001 - 横幅失败不阻断
        pass
    output.print(cards.empty_state())
    output.print(cards.gaps())
    return name


def output_channel(session: "_PS | None") -> AbstractContextManager[object]:
    """唯一的写终端通道包装。

    交互模式下 prompt 处于活跃状态而后台帧还在持续输出，不用 `patch_stdout`
    包裹就会互相撕屏（plan03 §2.4 第一条）。非 TTY（单次 prompt / 管道）没有
    prompt 在跑，直接直写。惰性导入：prompt_toolkit 仍是输入层可选依赖。
    """

    if session is None:
        return nullcontext()
    from prompt_toolkit.patch_stdout import patch_stdout

    return patch_stdout(raw=True)


async def submit(host: ServeHost, line: str) -> SubmitResult:
    """提交一行；返回服务端裁决（started / queued / 被拒）。"""
    response = await host.transport.request(
        "POST",
        f"{PREFIX}/submit",
        body=json.dumps({"line": line, "clientRequestId": os.urandom(8).hex()}).encode(),
    )
    payload = json.loads(response.body)
    if response.status >= 400:
        print(f"[拒绝] {payload.get('code')}: {payload.get('message')}", file=sys.stderr)
        return SubmitResult(turn_id=None, state="refused")
    return SubmitResult(
        turn_id=str(payload.get("turnId") or "") or None,
        state=str(payload.get("state", "started")),
    )


async def drain_pending(renderer: TerminalRenderer, *, timeout: float = 300.0) -> None:
    """EOF 前把已受理的回合收完（Ctrl-D 不应该把正在跑的回答吞掉）。"""

    budget = timeout
    while renderer.pending_turns > 0:
        renderer.done.clear()
        try:
            await asyncio.wait_for(renderer.done.wait(), timeout=budget)
        except TimeoutError:
            return


async def history_rows(host: ServeHost) -> list[dict[str, Any]]:
    """`/history` → 面板行（只读 transcript 浏览）。"""

    response = await host.transport.request("GET", f"{PREFIX}/history")
    if response.status >= 400:
        raise RuntimeError(f"history {response.status}")
    payload = json.loads(response.body)
    rows: list[dict[str, Any]] = []
    for position, message in enumerate(payload.get("messages", []), start=1):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role", "assistant"))
        first = ""
        for block in message.get("blocks", []):
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                first = str(block["text"]).strip().splitlines()[0]
                break
        rows.append({"id": str(position), "label": f"{position}. {role}", "detail": first})
    return rows


async def command_rows(host: ServeHost) -> list[dict[str, Any]]:
    """`/commands` → 面板行（`:help` 的数据源，与补全菜单同源）。"""

    rows: list[dict[str, Any]] = []
    for command in await fetch_commands(host):
        name = str(command.get("name", ""))
        if not name:
            continue
        aliases = [str(alias) for alias in command.get("aliases", []) or []]
        label = f"/{name}" + (f"  ({', '.join('/' + a for a in aliases)})" if aliases else "")
        rows.append({"id": f"/{name}", "label": label, "detail": str(command.get("description", ""))})
    return rows


async def open_panel(host: ServeHost, renderer: TerminalRenderer, line: str) -> str | None:
    """`:` 开头的本地面板入口：拉数据 → 打开面板 → 返回要提交的命令。"""

    panel = pickers.resolve(line)
    if panel is None:
        renderer.show(pickers.list_hint())
        return None
    try:
        if panel.kind == "transcript":
            # 只读 transcript：数据已在会话里，走 `/history`，不动 catalog。
            items = await history_rows(host)
        elif panel.kind == "help":
            # 只读命令面板：与补全菜单同源（禁硬编码清单）。
            items = await command_rows(host)
        else:
            response = await host.transport.request("GET", f"{PREFIX}/catalog/{panel.kind}")
            payload = json.loads(response.body)
            if response.status >= 400:
                renderer.show(
                    strings.PANEL_UNAVAILABLE.format(reason=payload.get("code", "error"))
                )
                return None
            items = [dict(item) for item in payload.get("items", [])]
    except Exception as exc:  # noqa: BLE001 - 面板取数失败不得影响 REPL
        renderer.show(strings.PANEL_UNAVAILABLE.format(reason=exc))
        return None
    if not items:
        renderer.show(strings.PANEL_EMPTY)
        return None
    chosen = await asyncio.to_thread(pickers.open_panel, panel, items)
    return pickers.action_line(panel, chosen)


async def drive_turns(
    host: ServeHost,
    renderer: TerminalRenderer,
    session: "_PS | None",
    prompt: str | None,
) -> int:
    """提交循环：单次 prompt 等回合结束；交互模式不阻塞等 done，排队交给服务端。"""

    if prompt:
        result = await submit(host, prompt)
        if result.turn_id is None:
            return 1
        if result.state == "queued":
            renderer.note_queued()
        await renderer.done.wait()
        return 0
    while True:
        line = await read_line(session)
        if line == EOF:
            await drain_pending(renderer)
            return 0
        if line == INTERRUPT:
            # 回合中 Ctrl-C = 取消；空闲时只是清掉当前行（什么都不做）。
            if renderer.busy:
                await host.transport.request("POST", f"{PREFIX}/cancel")
                renderer.note_cancel_requested()
            continue
        if not line.strip():
            continue
        line = paste.normalize(line)
        if line.startswith(":"):
            # 面板是终端本地能力（只读 catalog / history），选中后回到正常提交链。
            action = await open_panel(host, renderer, line)
            if action is None:
                continue
            line = action
        result = await submit(host, line)
        if result.turn_id is not None:
            renderer.expect_turn()
        if result.state == "queued":
            renderer.note_queued()
        # 不阻塞等本回合：读下一行，服务端的排队槽负责顺序与互斥。


async def run_terminal_client(
    host: ServeHost,
    *,
    prompt: str | None = None,
    console: Console | None = None,
) -> int:
    """跑交互循环（或单次 prompt），直到 EOF / 回合结束。"""
    output = console or Console()
    events = await host.transport.request("GET", f"{PREFIX}/events")
    assert events.stream is not None
    interactive = prompt is None and sys.stdin.isatty()
    profile_name = await print_banner(host, output) if interactive else "?"
    renderer = TerminalRenderer(host, output, profile_name=profile_name)
    consumer = asyncio.create_task(renderer.consume(events.stream))
    session = None
    if interactive:
        session = build_prompt_session(await fetch_commands(host))
    try:
        with output_channel(session):
            return await drive_turns(host, renderer, session, prompt)
    except KeyboardInterrupt:
        await host.transport.request("POST", f"{PREFIX}/cancel")
        output.print("[dim]已请求取消[/dim]")
        return 130
    finally:
        consumer.cancel()
        await asyncio.gather(consumer, return_exceptions=True)
