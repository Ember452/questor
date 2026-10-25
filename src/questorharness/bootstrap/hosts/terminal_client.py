"""终端瘦客户端：复用 serve 路由与 wire 帧，不复制业务与状态投影。

REPL 与 Studio 走同一套端点（submit / cancel / approve / ask / events / commands），
只是 transport 换成进程内实现、渲染器换成 rich。
输入层用 prompt_toolkit（斜杠补全菜单 + ↑↓ 历史），缺失或非 TTY 时回退裸 input。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import Console

from questorharness.bootstrap.hosts.serve import terminal_theme as theme
from questorharness.bootstrap.hosts.serve.authority import Authority
from questorharness.bootstrap.hosts.serve.host import ServeHost
from questorharness.bootstrap.hosts.terminal import approval as limits
from questorharness.bootstrap.hosts.terminal import cards, footer, paste, strings
from questorharness.bootstrap.hosts.terminal import wire_view as view
from questorharness.bootstrap.runtime import build_runtime
from questorharness.profiles import load_profile

if TYPE_CHECKING:
    from prompt_toolkit import PromptSession

    _PS = PromptSession[Any]

_PREFIX = "/rt/r1"
_EOF = "__questor_eof__"
_INTERRUPT = "__questor_interrupt__"


@dataclass(frozen=True)
class SubmitResult:
    """提交裁决：started / queued / 被拒（turn_id 为 None）。"""

    turn_id: str | None
    state: str


def default_profile_root() -> Path:
    """默认形态目录：优先环境变量，其次产品侧 bundle 目录。"""
    override = os.environ.get("QUESTOR_PROFILE_ROOT")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "questor" / "profiles"


def _frame_from_sse(block: bytes) -> dict[str, Any] | None:
    """从一条 SSE 事件块里取出 data 帧。"""
    for line in block.splitlines():
        if line.startswith(b"data: "):
            try:
                parsed = json.loads(line[len(b"data: ") :])
            except json.JSONDecodeError:
                return None
            return parsed if isinstance(parsed, dict) else None
    return None


def completion_catalog(commands: list[dict[str, Any]]) -> dict[str, str]:
    """指令目录 → 补全元数据（主名 + 别名 → 描述）。纯函数，供单测。"""
    catalog: dict[str, str] = {}
    for command in commands:
        catalog[f"/{command['name']}"] = str(command.get("description", ""))
        for alias in command.get("aliases", []) or []:
            catalog.setdefault(f"/{alias}", str(command.get("description", "")))
    return catalog


def _build_prompt_session(commands: list[dict[str, Any]]) -> "_PS | None":
    """有 prompt_toolkit 且在 TTY 上时建交互会话；否则返回 None（回退裸 input）。"""
    # 惰性导入：prompt_toolkit 是输入层的可选依赖，不能拖进包根的冷导入路径。
    from questorharness.bootstrap.hosts.terminal import input_session

    catalog = completion_catalog(commands)
    history_path = Path.home() / ".questorharness" / "terminal_history"
    return input_session.build(catalog, history_path=history_path)


def _prompt_once(session: "_PS") -> str:
    """同步读一行：Ctrl-C 交回中断哨兵（回合中会变成 /cancel）。运行在 worker 线程。"""
    while True:
        try:
            text: str = session.prompt("> ")
            return text
        except KeyboardInterrupt:
            return _INTERRUPT


async def _read_line(session: "_PS | None") -> str:
    """读一行输入；EOF / Ctrl-C 各走一个哨兵。session 为空时回退裸 input。"""
    if session is None:
        try:
            return await asyncio.to_thread(input, "> ")
        except EOFError:
            return _EOF
        except KeyboardInterrupt:
            return _INTERRUPT
    try:
        return await asyncio.to_thread(_prompt_once, session)
    except EOFError:
        return _EOF


async def _fetch_commands(host: ServeHost) -> list[dict[str, Any]]:
    """指令目录（补全菜单数据源）；失败回空列表，不阻断 REPL。"""
    try:
        response = await host.transport.request("GET", f"{_PREFIX}/commands")
        payload = json.loads(response.body)
        return list(payload.get("commands", []))
    except Exception:  # noqa: BLE001 - 补全是增强体验，缺席可用
        return []


async def _print_banner(host: ServeHost, output: Console) -> str:
    """交互模式横幅：Reasonix ASCII art + 形态 + 用法提示；返回形态名供状态栏用。"""
    output.print(cards.banner())
    name = "?"
    try:
        response = await host.transport.request("GET", f"{_PREFIX}/profile")
        profile = json.loads(response.body)
        name = str(profile.get("name", "?"))
        output.print(
            f"[bold]{name}[/bold] · {profile.get('description', '')}",
            style=theme.DIM,
        )
    except Exception:  # noqa: BLE001 - 横幅失败不阻断
        pass
    output.print(cards.empty_state())
    return name


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

    async def consume(self, stream: AsyncIterator[bytes]) -> None:
        """持续消费 SSE 字节流。"""
        buffer = b""
        async for chunk in stream:
            buffer += chunk
            while b"\n\n" in buffer:
                block, buffer = buffer.split(b"\n\n", 1)
                if not block.startswith(b"id:"):
                    continue
                frame = _frame_from_sse(block)
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
        """状态栏：形态/忙闲/队列是真值，其余字段在波 D 前显式渲染 `—`。"""

        return footer.render(
            footer.FooterVM(
                profile=self._profile_name, busy=self._busy, queue_depth=self._queue_depth
            )
        )

    async def _ask_approval(self, item: view.ApprovalItem) -> None:
        """审批：y 通过，其余拒绝（fail-closed 由服务端兼底）。编辑类先给 diff 卡。"""
        self._console.print(cards.render_item(item))
        self._console.print(limits.deadline_hint(self._prompt_timeout()), style=theme.DIM)
        answer = await self._read_answer("  [y/N] 允许执行? ")
        if answer is None:
            self._console.print(strings.APPROVAL_TIMEOUT, style=theme.WARN)
        decision = "approve" if (answer or "").strip().lower() in {"y", "yes"} else "deny"
        await self._host.transport.request(
            "POST",
            f"{_PREFIX}/approve",
            body=json.dumps({"id": item.prompt_id, "decision": decision}).encode(),
        )

    async def _answer_question(self, item: view.AskItem) -> None:
        """工具提问：空输入即视为未回答；客户端与同一个超时对齐。"""
        self._console.print(cards.render_item(item))
        self._console.print(
            limits.deadline_hint(self._prompt_timeout(), kind="提问"), style=theme.DIM
        )
        answer = await self._read_answer("  → ")
        if answer is None:
            self._console.print(strings.ASK_TIMEOUT, style=theme.WARN)
        await self._host.transport.request(
            "POST",
            f"{_PREFIX}/ask",
            body=json.dumps({"id": item.prompt_id, "answer": answer or ""}).encode(),
        )

    def _prompt_timeout(self) -> float:
        """服务端的提示超时（authority 默认 300s）；拿不到就用契约默认值。"""

        return float(getattr(self._host.authority, "prompt_timeout", limits.DEFAULT_TIMEOUT_SECONDS))

    async def _read_answer(self, prompt: str) -> str | None:
        """读一个回答；超时返回 None，让调用方按 fail-closed 结算。"""

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(input, prompt), timeout=self._prompt_timeout()
            )
        except TimeoutError:
            return None


async def _submit(host: ServeHost, line: str) -> SubmitResult:
    """提交一行；返回服务端裁决（started / queued / 被拒）。"""
    response = await host.transport.request(
        "POST",
        f"{_PREFIX}/submit",
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


async def _drain_pending(renderer: TerminalRenderer, *, timeout: float = 300.0) -> None:
    """EOF 前把已受理的回合收完（Ctrl-D 不应该把正在跑的回答吞掉）。"""

    budget = timeout
    while renderer.pending_turns > 0:
        renderer.done.clear()
        try:
            await asyncio.wait_for(renderer.done.wait(), timeout=budget)
        except TimeoutError:
            return


async def run_terminal_client(
    host: ServeHost,
    *,
    prompt: str | None = None,
    console: Console | None = None,
) -> int:
    """跑交互循环（或单次 prompt），直到 EOF / 回合结束。"""
    output = console or Console()
    events = await host.transport.request("GET", f"{_PREFIX}/events")
    assert events.stream is not None
    interactive = prompt is None and sys.stdin.isatty()
    profile_name = await _print_banner(host, output) if interactive else "?"
    renderer = TerminalRenderer(host, output, profile_name=profile_name)
    consumer = asyncio.create_task(renderer.consume(events.stream))
    session = None
    if interactive:
        session = _build_prompt_session(await _fetch_commands(host))
    try:
        if prompt:
            result = await _submit(host, prompt)
            if result.turn_id is None:
                return 1
            if result.state == "queued":
                renderer.note_queued()
            await renderer.done.wait()
            return 0
        while True:
            line = await _read_line(session)
            if line == _EOF:
                await _drain_pending(renderer)
                return 0
            if line == _INTERRUPT:
                # 回合中 Ctrl-C = 取消；空闲时只是清掉当前行（什么都不做）。
                if renderer.busy:
                    await host.transport.request("POST", f"{_PREFIX}/cancel")
                    renderer.note_cancel_requested()
                continue
            if not line.strip():
                continue
            line = paste.normalize(line)
            result = await _submit(host, line)
            if result.turn_id is not None:
                renderer.expect_turn()
            if result.state == "queued":
                renderer.note_queued()
            # 不阻塞等本回合：读下一行，服务端的排队槽负责顺序与互斥。

    except KeyboardInterrupt:
        await host.transport.request("POST", f"{_PREFIX}/cancel")
        output.print("[dim]已请求取消[/dim]")
        return 130
    finally:
        consumer.cancel()
        await asyncio.gather(consumer, return_exceptions=True)


def merge_tool_overrides(
    profile: Any, overrides: Mapping[str, object] | None
) -> dict[str, Any]:
    """合并工具面：覆盖只许收窄；None 或缺省 → 用 profile 值。"""
    extra: dict[str, Any] = dict(overrides or {})
    if extra.get("allowed_tools") is None:
        extra["allowed_tools"] = list(profile.allowed_tools)
    if extra.get("denied_tools") is None:
        extra["denied_tools"] = list(profile.denied_tools)
    return extra


async def build_serve_host(
    *,
    cwd: str | None = None,
    model: str | None = None,
    max_turns: int | None = None,
    effort: str | None = None,
    base_url: str | None = None,
    system_prompt: str | None = None,
    api_key: str | None = None,
    api_format: str | None = None,
    api_client: Any = None,
    restore_messages: list[dict[str, Any]] | None = None,
    restore_tool_metadata: dict[str, object] | None = None,
    permission_mode: str | None = None,
    profile_root: Path | None = None,
    profile_id: str = "coding",
    overrides: Mapping[str, object] | None = None,
) -> ServeHost:
    """装配 runtime 与 serve 宿主（REPL 与 Studio 共用）。"""
    authority = Authority()
    root = profile_root or default_profile_root()
    profile = load_profile(root, profile_id)
    extra = merge_tool_overrides(profile, overrides)
    runtime = await build_runtime(
        cwd=cwd,
        model=model,
        max_turns=max_turns,
        effort=effort,
        base_url=base_url,
        system_prompt=system_prompt,
        api_key=api_key,
        api_format=api_format,
        api_client=api_client,
        restore_messages=restore_messages,
        restore_tool_metadata=restore_tool_metadata,
        enforce_max_turns=max_turns is not None,
        permission_mode=permission_mode,
        permission_prompt=authority.permission_prompt,
        ask_user_prompt=authority.ask_user_prompt,
        edit_approval_prompt=authority.edit_approval_prompt,
        **extra,
    )
    return ServeHost(
        runtime,
        authority=authority,
        profile_root=root,
        profile_id=profile_id,
    )


async def run_terminal_repl(
    *,
    prompt: str | None = None,
    cwd: str | None = None,
    model: str | None = None,
    max_turns: int | None = None,
    effort: str | None = None,
    base_url: str | None = None,
    system_prompt: str | None = None,
    api_key: str | None = None,
    api_format: str | None = None,
    api_client: Any = None,
    restore_messages: list[dict[str, Any]] | None = None,
    restore_tool_metadata: dict[str, object] | None = None,
    permission_mode: str | None = None,
    profile_root: Path | None = None,
    overrides: Mapping[str, object] | None = None,
) -> int:
    """装配 runtime + serve 宿主，然后进入终端循环。"""
    host = await build_serve_host(
        cwd=cwd,
        model=model,
        max_turns=max_turns,
        effort=effort,
        base_url=base_url,
        system_prompt=system_prompt,
        api_key=api_key,
        api_format=api_format,
        api_client=api_client,
        restore_messages=restore_messages,
        restore_tool_metadata=restore_tool_metadata,
        permission_mode=permission_mode,
        profile_root=profile_root,
        overrides=overrides,
    )
    await host.start()
    try:
        return await run_terminal_client(host, prompt=prompt)
    finally:
        await host.close()
