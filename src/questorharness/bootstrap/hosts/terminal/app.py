"""REPL 装配与会话循环：唯一写终端通道、单次/交互两种模式、面板入口。

这一层只做"读一行 → 提交 → 收帧渲染"的调度；渲染在 `renderer`，视图模型在
`wire_view`，图元在 `cards`，输入在 `input_session`，键位在 `keymap`。

三条硬约定（plan03 §2.4）：
1. 唯一写终端通道 = 本模块的 `output_channel`；
2. 输入只有**一个** PromptSession：审批/提问是它的模态（`renderer.answer_pending`），
   不再另起第二个 Application——那是 Windows 上 "Executor shutdown" 堆栈的来源；
3. `/` 开头但解析不到的行**不得**漏给模型（会变成"模型跑去执行 bash"），
   本地提示 + 直接开命令面板。
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
from rich.text import Text

from questorharness.bootstrap.hosts.serve import terminal_theme as theme
from questorharness.bootstrap.hosts.serve.host import ServeHost
from questorharness.bootstrap.hosts.terminal import cards, paste, pickers, strings
from questorharness.bootstrap.hosts.terminal.output import console as build_console
from questorharness.bootstrap.hosts.terminal.renderer import TerminalRenderer

if TYPE_CHECKING:
    from prompt_toolkit import PromptSession

    _PS = PromptSession[Any]

PREFIX = "/rt/r1"
EOF = "__questor_eof__"
INTERRUPT = "__questor_interrupt__"


@dataclass(frozen=True)
class SubmitResult:
    """提交裁决：started / queued / 被拒（turn_id 为 None，detail 带拒绝码）。"""

    turn_id: str | None
    state: str
    detail: str = ""


def completion_catalog(commands: list[dict[str, Any]]) -> dict[str, str]:
    """指令目录 → 补全元数据（主名 + 别名 → 描述）。纯函数，供单测。"""

    catalog: dict[str, str] = {}
    for command in commands:
        catalog[f"/{command['name']}"] = str(command.get("description", ""))
        for alias in command.get("aliases", []) or []:
            catalog.setdefault(f"/{alias}", str(command.get("description", "")))
    return catalog


def unknown_command_name(line: str, catalog: dict[str, str]) -> str | None:
    """`/` 开头但目录里没有的那个名字；不是斜杠输入或命中则 None。

    只认第一个词（`/model gpt` 的名字是 `/model`）。空目录（补全取数失败）
    不当成"全都未知"——那会让所有斜杠命令都发不出去，宁可放行交给引擎。
    """

    if not catalog or not line.startswith("/"):
        return None
    name = line.split(maxsplit=1)[0]
    return None if name in catalog else name


def command_list_text(catalog: dict[str, str], *, limit: int = 24) -> str:
    """命令目录 → 一段可直接看的清单（不依赖浮动菜单/二次交互）。"""

    items = [f"  {name:<22}{description}" for name, description in list(catalog.items())[:limit]]
    lead = strings.COMMAND_LIST_LEAD.format(shown=len(items))
    return "\n".join([lead, *items])


def build_prompt_session(commands: list[dict[str, Any]]) -> "_PS | None":
    """有 prompt_toolkit 且在 TTY 上时建交互会话；否则返回 None（回退裸 input）。"""
    # 惰性导入：输入层与键位都不属包根的冷导入路径（prompt_toolkit 是可选依赖）。
    from questorharness.bootstrap.hosts.terminal import input_session, keymap

    catalog = completion_catalog(commands)
    history_path = Path.home() / ".questorharness" / "terminal_history"
    return input_session.build(
        catalog,
        history_path=history_path,
        key_bindings=keymap.build(),
    )


async def read_line(session: "_PS | None") -> str:
    """读一行输入；EOF / Ctrl-C 各走一个哨兵。

    TTY 上走 `prompt_async`（同一个 event loop）：用 `asyncio.to_thread` 包
    `session.prompt()` 会让 prompt_toolkit 在工作线程里 `asyncio.run()` 另建
    一个 loop，并在 prompt 结束时关掉默认 executor——win32 句柄回调随后触发
    `RuntimeError: Executor shutdown has been called`，每次读行刷一屏堆栈。
    """

    if session is None:
        try:
            return await asyncio.to_thread(input, strings.prompt_marker())
        except EOFError:
            return EOF
        except KeyboardInterrupt:
            return INTERRUPT
    try:
        text: str = await session.prompt_async(strings.prompt_marker())
        return text
    except EOFError:
        return EOF
    except KeyboardInterrupt:
        return INTERRUPT


async def fetch_commands(host: ServeHost) -> list[dict[str, Any]]:
    """指令目录（补全菜单数据源）；失败回空列表，不阻断 REPL。"""
    try:
        response = await host.transport.request("GET", f"{PREFIX}/commands")
        payload = json.loads(response.body)
        return list(payload.get("commands", []))
    except Exception:  # noqa: BLE001 - 补全是增强体验，缺席可用
        return []


async def profile_info(host: ServeHost) -> tuple[str, str]:
    """`/profile` → (名称, 描述)；取不到就返 (`?`, 空)。非交互模式也要拿名称供状态栏用。"""

    try:
        response = await host.transport.request("GET", f"{PREFIX}/profile")
        profile = json.loads(response.body)
    except Exception:  # noqa: BLE001 - 横幅/状态栏失败不阻断
        return "?", ""
    return str(profile.get("name", "?")), str(profile.get("description", ""))


async def print_banner(host: ServeHost, output: Console) -> str:
    """交互模式横幅：一行品牌 + 形态 + 空态 + 能力缺口；返回形态名供状态栏用。"""

    output.print(cards.banner())
    name, description = await profile_info(host)
    output.print(_profile_line(name, description))
    output.print(cards.empty_state())
    output.print(cards.gaps())
    return name


def _profile_line(name: str, description: str) -> Text:
    """`形态 · 描述` 一行（用 Text 而不是 markup 字符串，避免文案被解析）。"""

    text = Text()
    text.append(name, style=theme.BOLD)
    if description:
        text.append(f" · {description}", style=theme.DIM)
    return text


def output_channel(session: "_PS | None") -> AbstractContextManager[object]:
    """写终端通道。

    不再用 `patch_stdout` 包住整个循环：那会把回合中每一条流式输出都变成
    "擦掉 prompt → 写 → 重绘 prompt"，在 Windows 控制台上直接表现为
    分界线/状态栏与正文粘成一行（实跑截图里 `+1/-0──────…` 就是它）。
    改为**回合内不读行**（见 `drive_turns`）：prompt 只在空闲时存在，
    输出与 prompt 不会同时写屏。
    """

    return nullcontext()


async def submit(host: ServeHost, line: str) -> SubmitResult:
    """提交一行；返回服务端裁决（started / queued / 被拒）。"""
    response = await host.transport.request(
        "POST",
        f"{PREFIX}/submit",
        body=json.dumps({"line": line, "clientRequestId": os.urandom(8).hex()}).encode(),
    )
    payload = json.loads(response.body)
    if response.status >= 400:
        # 不走 stderr 裸 print：拒绝码随 SubmitResult 回调用方，经 renderer 呈现。
        detail = f"{payload.get('code')}: {payload.get('message')}"
        return SubmitResult(turn_id=None, state="refused", detail=detail)
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
    """`/commands` → 面板行（`:help` 的数据源，与补全菜单同源）。

    行带 `group`（命令族），由面板渲染成族标题（plan03 T18/C2）。
    """

    rows: list[dict[str, Any]] = []
    for command in await fetch_commands(host):
        name = str(command.get("name", ""))
        if not name:
            continue
        aliases = [str(alias) for alias in command.get("aliases", []) or []]
        label = f"/{name}" + (f"  ({', '.join('/' + a for a in aliases)})" if aliases else "")
        rows.append(
            {
                "id": f"/{name}",
                "label": label,
                "detail": str(command.get("description", "")),
                "group": str(command.get("family", "")),
            }
        )
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
    chosen = await pickers.open_panel(panel, items)
    return pickers.action_line(panel, chosen)


async def drive_turns(
    host: ServeHost,
    renderer: TerminalRenderer,
    session: "_PS | None",
    prompt: str | None,
    catalog: dict[str, str] | None = None,
) -> int:
    """提交循环：单次 prompt 等回合结束；交互模式不阻塞等 done，排队交给服务端。"""

    known = catalog or {}

    if prompt:
        result = await submit(host, prompt)
        if result.turn_id is None:
            if result.detail:
                renderer.show(strings.SUBMIT_REFUSED.format(detail=result.detail))
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
            if renderer.has_pending_prompt:
                # 审批/提问中按 Ctrl-C = 拒绝/未回答，不得把整轮打断。
                await renderer.answer_pending("")
                continue
            # 回合中 Ctrl-C = 取消；空闲时只是清掉当前行（什么都不做）。
            if renderer.busy:
                await host.transport.request("POST", f"{PREFIX}/cancel")
                renderer.note_cancel_requested()
            continue
        if renderer.has_pending_prompt:
            # 这一行是答案，不是新消息：空行也算（= 未回答 / 默认拒绝）。
            await renderer.answer_pending(line)
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
        unknown = unknown_command_name(line, known)
        if unknown is not None:
            # 未知指令绝不发给模型（否则模型会"帮你查"，然后开始跑 bash）。
            # 直接把清单打出来，不再要求第二次交互（面板需要 TTY 且多一次回车）。
            renderer.show(strings.UNKNOWN_COMMAND.format(name=unknown))
            renderer.show(command_list_text(known))
            continue
        # 先清 done 再提交：否则上一回合残留的 set 会让本轮“瞬间完成”，
        # 而提交后才清则会漏掉极快回合的 turn_done（两种都是悬挂 300s）。
        renderer.done.clear()
        result = await submit(host, line)
        if result.state == "refused":
            renderer.show(strings.SUBMIT_REFUSED.format(detail=result.detail))
            continue
        if result.turn_id is not None:
            renderer.expect_turn()
            # 回合内不读行：prompt 只在空闲时存在，正文/卡片不会被 prompt 重绘
            # 碾成一行。代价是不能在回合中排队新消息（换取“看得清”）。
            await renderer.done.wait()
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
    output = console or build_console()
    events = await host.transport.request("GET", f"{PREFIX}/events")
    assert events.stream is not None
    interactive = prompt is None and sys.stdin.isatty()
    commands = await fetch_commands(host) if prompt is None else []
    catalog = completion_catalog(commands)
    if interactive:
        profile_name = await print_banner(host, output)
    else:
        profile_name = (await profile_info(host))[0]
    renderer = TerminalRenderer(host, output, profile_name=profile_name)
    # 单次 prompt 没人替它读行 → 审批就地询问；REPL → 审批是主输入的模态。
    renderer.set_mode("loop" if prompt is None else "inline")
    await renderer.refresh_status()  # 状态栏四字段真值（fail-soft）
    consumer = asyncio.create_task(renderer.consume(events.stream))
    session = None
    if interactive:
        session = build_prompt_session(commands)
    try:
        with output_channel(session):
            return await drive_turns(host, renderer, session, prompt, catalog)
    except KeyboardInterrupt:
        await host.transport.request("POST", f"{PREFIX}/cancel")
        output.print("[dim]已请求取消[/dim]")
        return 130
    finally:
        consumer.cancel()
        await asyncio.gather(consumer, return_exceptions=True)
