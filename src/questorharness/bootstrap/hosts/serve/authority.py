"""单写者租约、幂等表、排队槽与三模态提示桥。

一个 RuntimeBundle 同时只允许一个 active turn；提示（approval / ask / edit）
以 Future 形式挂在这里，由 HTTP 路由结算——这正是旧 React 宿主的形状，
移植而非重新发明。提示打开时通过注入的 ``on_prompt`` 回调交给宿主广播。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from questorharness.bootstrap.hosts.serve import refusals

TurnState = Literal["running", "queued"]
BeginKind = Literal["started", "queued", "replay", "busy"]
PromptKind = Literal["approval", "ask"]

PromptNotifier = Callable[["PendingPrompt", str], None]


@dataclass
class TurnRecord:
    """一次提交的归属记录。"""

    turn_id: str
    client_id: str
    request_id: str
    state: TurnState
    line: str = ""
    via: str = "studio"
    created_at: float = field(default_factory=time.monotonic)


@dataclass(frozen=True)
class Begin:
    """begin() 的裁决结果。"""

    kind: BeginKind
    turn_id: str
    position: int | None = None


@dataclass
class PendingPrompt:
    """一个等待客户端作答的提示。"""

    prompt_id: str
    kind: PromptKind
    owner: str
    subject: str
    tool: str
    future: asyncio.Future[Any]
    detail: str = ""
    patch: str | None = None
    added: int | None = None
    removed: int | None = None
    # 提问选项（plan03 A2）：仅 `kind="ask"` 时有意义，None = 自由文本提问。
    options: list[str] | None = None


class Authority:
    """持有回合租约、幂等表与提示 Future 表。"""

    def __init__(
        self,
        *,
        queue_depth: int = 1,
        request_ttl: float = 120.0,
        prompt_timeout: float = 300.0,
        on_prompt: PromptNotifier | None = None,
    ) -> None:
        self._queue_depth = queue_depth
        self._request_ttl = request_ttl
        self._prompt_timeout = prompt_timeout
        self._on_prompt = on_prompt
        self._running: TurnRecord | None = None
        self._queued: TurnRecord | None = None
        self._requests: dict[str, TurnRecord] = {}
        self._prompts: dict[str, PendingPrompt] = {}
        self._index = 0

    # ---- 回合租约 -------------------------------------------------------
    def next_index(self) -> int:
        """回合序号（turn_started.index）。"""
        self._index += 1
        return self._index

    @property
    def active_turn(self) -> TurnRecord | None:
        """当前持有租约的回合。"""
        return self._running

    @property
    def prompt_timeout(self) -> float:
        """提示（审批/提问）的超时秒数；客户端要把同一个数字展示给用户。"""
        return self._prompt_timeout

    def is_owner(self, turn_id: str, client_id: str) -> bool:
        """判断客户端是否为该回合的持有者。"""
        running = self._running
        return running is not None and running.turn_id == turn_id and running.client_id == client_id

    def begin(self, client_id: str, request_id: str, line: str, *, via: str = "studio") -> Begin:
        """提交裁决：重放 / 入队 / 开新回合 / 忙。"""
        self._sweep()
        existing = self._requests.get(request_id)
        if existing is not None:
            return Begin(kind="replay", turn_id=existing.turn_id)
        if self._running is not None:
            if self._queued is None and self._queue_depth > 0:
                record = TurnRecord(
                    turn_id=uuid.uuid4().hex,
                    client_id=client_id,
                    request_id=request_id,
                    state="queued",
                    line=line,
                    via=via,
                )
                self._queued = record
                self._requests[request_id] = record
                return Begin(kind="queued", turn_id=record.turn_id, position=1)
            raise refusals.Refusal(refusals.TURN_BUSY, "a turn is already running")
        record = TurnRecord(
            turn_id=uuid.uuid4().hex,
            client_id=client_id,
            request_id=request_id,
            state="running",
            line=line,
            via=via,
        )
        self._running = record
        self._requests[request_id] = record
        return Begin(kind="started", turn_id=record.turn_id)

    def state_of(self, request_id: str) -> TurnState | None:
        """幂等重放的登记状态（排队中的请求不得被谎报为 started）。"""
        record = self._requests.get(request_id)
        return None if record is None else record.state

    def finish(self, turn_id: str) -> None:
        """回合结束，释放租约。"""
        if self._running is not None and self._running.turn_id == turn_id:
            self._running = None

    def pop_queued(self) -> TurnRecord | None:
        """取出排队回合并转为运行态（容量 1）。"""
        record = self._queued
        if record is None:
            return None
        self._queued = None
        record.state = "running"
        self._running = record
        return record

    def _sweep(self) -> None:
        """清理过期幂等记录，避免长跑进程内存增长。"""
        now = time.monotonic()
        active = {record.turn_id for record in (self._running, self._queued) if record is not None}
        expired = [
            key
            for key, record in self._requests.items()
            if record.turn_id not in active and now - record.created_at > self._request_ttl
        ]
        for key in expired:
            self._requests.pop(key, None)

    # ---- 三模态提示 -----------------------------------------------------
    def set_notifier(self, notifier: PromptNotifier | None) -> None:
        """注入提示广播回调（宿主在构造时接线）。"""
        self._on_prompt = notifier

    async def permission_prompt(
        self,
        tool: str,
        subject: str,
        *,
        detail: str = "",
        patch: str | None = None,
        added: int | None = None,
        removed: int | None = None,
    ) -> bool:
        """权限审批：超时或无人作答时 fail-closed。"""
        prompt = self._open(
            "approval", subject, tool=tool, detail=detail, patch=patch, added=added, removed=removed
        )
        try:
            return bool(await asyncio.wait_for(prompt.future, timeout=self._prompt_timeout))
        except TimeoutError:
            return False
        finally:
            self._prompts.pop(prompt.prompt_id, None)

    async def ask_user_prompt(
        self, question: str, options: list[str] | None = None
    ) -> str:
        """工具提问：超时返回空串（调用方按"未回答"处理）。

        `options` 只是随提示登记的候选（plan03 A2）：结算仍走同一个 `/ask` 通道，
        客户端可以用序号回答，也可以回原文。
        """
        prompt = self._open("ask", question, options=options)
        try:
            answer = await asyncio.wait_for(prompt.future, timeout=self._prompt_timeout)
        except TimeoutError:
            return ""
        finally:
            self._prompts.pop(prompt.prompt_id, None)
        return str(answer)

    async def edit_approval_prompt(self, path: str, diff: str, added: int, removed: int) -> str:
        """编辑审批：复用 approval 槽位，返回 approve / deny。

        diff 不能丢：旧 UI 能看到改了什么，新协议至少给出 +added/-removed 与
        截断后的补丁正文（上限 4000 字符），供 ApprovalCard 展示。结构化字段
        （patch/added/removed）与旧的 detail 同时存在：前者给新客户端画 diff 卡，
        后者保证旧消费者行为不变。
        """
        patch = diff[:4000]
        detail = f"+{added}/-{removed}" + (f"\n{patch}" if patch else "")
        approved = await self.permission_prompt(
            "edit", path, detail=detail, patch=patch, added=added, removed=removed
        )
        return "approve" if approved else "deny"

    def _open(
        self,
        kind: PromptKind,
        subject: str,
        *,
        tool: str = "",
        detail: str = "",
        patch: str | None = None,
        added: int | None = None,
        removed: int | None = None,
        options: list[str] | None = None,
    ) -> PendingPrompt:
        """登记一个待答提示，并通过回调交给宿主广播。"""
        loop = asyncio.get_running_loop()
        owner = self._running.client_id if self._running is not None else ""
        prompt = PendingPrompt(
            prompt_id=uuid.uuid4().hex,
            kind=kind,
            owner=owner,
            subject=subject,
            tool=tool,
            detail=detail,
            patch=patch,
            added=added,
            removed=removed,
            options=list(options) if options else None,
            future=loop.create_future(),
        )
        self._prompts[prompt.prompt_id] = prompt
        if self._on_prompt is not None:
            self._on_prompt(prompt, subject)
        return prompt

    def settle(self, prompt_id: str, value: Any, client_id: str) -> None:
        """结算提示：非持有者与重复结算各有独立拒绝码。"""
        not_owner = refusals.ASK_NOT_OWNER if type(value) is str else refusals.APPROVAL_NOT_OWNER
        settled = (
            refusals.ASK_ALREADY_SETTLED
            if type(value) is str
            else refusals.APPROVAL_ALREADY_SETTLED
        )
        prompt = self._prompts.get(prompt_id)
        if prompt is None:
            raise refusals.Refusal(settled, "prompt already settled or unknown")
        if prompt.kind == "ask":
            not_owner, settled = refusals.ASK_NOT_OWNER, refusals.ASK_ALREADY_SETTLED
        if prompt.owner and client_id != prompt.owner:
            raise refusals.Refusal(not_owner, "prompt owned by another client")
        if prompt.future.done():
            raise refusals.Refusal(settled, "prompt already settled")
        prompt.future.set_result(value)

    def pending(self, prompt_id: str) -> PendingPrompt | None:
        """查询提示（测试与路由共用）。"""
        return self._prompts.get(prompt_id)
