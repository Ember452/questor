"""终端瘦客户端：复用 serve 路由与 wire 帧，不复制业务与状态投影。

REPL 与 Studio 走同一套端点（submit / cancel / approve / ask / events），
只是 transport 换成进程内实现、渲染器换成 rich。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any

from rich.console import Console

from questorharness.bootstrap.hosts.serve.authority import Authority
from questorharness.bootstrap.hosts.serve.host import ServeHost
from questorharness.bootstrap.runtime import build_runtime
from questorharness.profiles import load_profile

_PREFIX = "/rt/r1"


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


class TerminalRenderer:
    """把 wire 帧渲染到终端，并把审批/提问回灌成 HTTP 调用。"""

    def __init__(self, host: ServeHost, console: Console) -> None:
        self._host = host
        self._console = console
        self._streaming = False
        self.done = asyncio.Event()

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
        """按 kind 渲染；审批/提问直接就地询问。"""
        kind = frame.get("kind")
        if kind == "turn_started":
            self._console.print(f"[dim]── turn {frame.get('turnId', '')[:8]} ──[/dim]")
        elif kind == "text":
            self._console.print(str(frame.get("text", "")), end="", soft_wrap=True)
            self._streaming = True
        elif kind == "message":
            if self._streaming:
                self._console.print()
                self._streaming = False
        elif kind == "tool_dispatch":
            self._console.print(f"[cyan]▸ {frame.get('tool')}[/cyan]")
        elif kind == "tool_result":
            state = "[red]错误[/red]" if frame.get("isError") else "[green]完成[/green]"
            preview = str(frame.get("output", "")).strip().splitlines()
            head = preview[0][:120] if preview else ""
            self._console.print(f"  {state} {frame.get('tool')}: {head}")
        elif kind == "notice":
            self._console.print(f"[yellow]{frame.get('text', '')}[/yellow]")
        elif kind in {"compaction_started", "compaction_progress", "compaction_done"}:
            self._console.print(f"[dim]{kind} {frame.get('phase', '')}[/dim]")
        elif kind == "approval_request":
            await self._ask_approval(frame)
        elif kind == "ask_request":
            await self._answer_question(frame)
        elif kind == "turn_done":
            outcome = frame.get("outcome")
            self._console.print(f"[dim]── {outcome} ({frame.get('durationMs')}ms) ──[/dim]")
            self.done.set()

    async def _ask_approval(self, frame: dict[str, Any]) -> None:
        """审批：y 通过，其余拒绝（fail-closed 由服务端兜底）。编辑类先给 diff 摘要。"""
        detail = str(frame.get("detail") or "").strip()
        if detail:
            preview = "\n".join(detail.splitlines()[:6])
            self._console.print(f"[dim]{preview}[/dim]")
        prompt = f"允许 {frame.get('tool')} 执行 {frame.get('subject')}? [y/N] "
        answer = await asyncio.to_thread(input, prompt)
        decision = "approve" if answer.strip().lower() in {"y", "yes"} else "deny"
        await self._host.transport.request(
            "POST",
            f"{_PREFIX}/approve",
            body=json.dumps({"id": frame.get("id"), "decision": decision}).encode(),
        )

    async def _answer_question(self, frame: dict[str, Any]) -> None:
        """工具提问：空输入即视为未回答。"""
        answer = await asyncio.to_thread(input, f"? {frame.get('question')} ")
        await self._host.transport.request(
            "POST",
            f"{_PREFIX}/ask",
            body=json.dumps({"id": frame.get("id"), "answer": answer}).encode(),
        )


async def _submit(host: ServeHost, line: str) -> str | None:
    """提交一行；返回 turnId（busy/queued 时打印提示）。"""
    response = await host.transport.request(
        "POST",
        f"{_PREFIX}/submit",
        body=json.dumps({"line": line, "clientRequestId": os.urandom(8).hex()}).encode(),
    )
    payload = json.loads(response.body)
    if response.status >= 400:
        print(f"[拒绝] {payload.get('code')}: {payload.get('message')}", file=sys.stderr)
        return None
    if payload.get("state") == "queued":
        print("[排队] 当前回合结束后自动开始", file=sys.stderr)
    return str(payload.get("turnId"))


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
    renderer = TerminalRenderer(host, output)
    consumer = asyncio.create_task(renderer.consume(events.stream))
    try:
        if prompt:
            await _submit(host, prompt)
            await renderer.done.wait()
            return 0
        while True:
            try:
                line = await asyncio.to_thread(input, "> ")
            except EOFError:
                return 0
            if not line.strip():
                continue
            renderer.done.clear()
            turn = await _submit(host, line)
            if turn is None:
                continue
            await renderer.done.wait()
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
    restore_messages: list[dict] | None = None,
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
    restore_messages: list[dict] | None = None,
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
