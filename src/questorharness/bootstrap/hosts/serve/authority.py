"""单写者租约、幂等表、排队槽与三模态提示桥。

一个 RuntimeBundle 同时只允许一个 active turn；提示（approval / ask / edit）
以 Future 形式挂在这里，由 HTTP 路由结算——这正是原 backend_host 的形状，
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

    def is_owner(self, turn_id: str, client_id: str) -> bool:
        """判断客户端是否为该回合的持有者。"""
        running = self._running
        return running is not None and running.turn_id == turn_id and running.client_id == client_id

    def begin(self, client_id: str, request_id: str, line: str) -> Begin:
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
        )
        self._running = record
        self._requests[request_id] = record
        return Begin(kind="started", turn_id=record.turn_id)

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

    async def permission_prompt(self, tool: str, subject: str) -> bool:
        """权限审批：超时或无人作答时 fail-closed。"""
        prompt = self._open("approval", subject, tool=tool)
        try:
            return bool(await asyncio.wait_for(prompt.future, timeout=self._prompt_timeout))
        except TimeoutError:
            return False
        finally:
            self._prompts.pop(prompt.prompt_id, None)

    async def ask_user_prompt(self, question: str) -> str:
        """工具提问：超时返回空串（调用方按"未回答"处理）。"""
        prompt = self._open("ask", question)
        try:
            answer = await asyncio.wait_for(prompt.future, timeout=self._prompt_timeout)
        except TimeoutError:
            return ""
        finally:
            self._prompts.pop(prompt.prompt_id, None)
        return str(answer)

    async def edit_approval_prompt(self, path: str, diff: str, added: int, removed: int) -> str:
        """编辑审批：复用 approval 槽位，返回 approve / deny。"""
        del diff, added, removed
        approved = await self.permission_prompt("edit", path)
        return "approve" if approved else "deny"

    def _open(self, kind: PromptKind, subject: str, *, tool: str = "") -> PendingPrompt:
        """登记一个待答提示，并通过回调交给宿主广播。"""
        loop = asyncio.get_running_loop()
        owner = self._running.client_id if self._running is not None else ""
        prompt = PendingPrompt(
            prompt_id=uuid.uuid4().hex,
            kind=kind,
            owner=owner,
            subject=subject,
            tool=tool,
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
