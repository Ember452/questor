"""L5 Port 协议（design/00 §3.1；HARD C1/C4/C9/C12）。

Port 是最内层的抽象接口；具体适配器（LiteLLM、SQLite、沙箱后端）住在
:mod:`questor.providers`，以**注入**方式交给内核。内核只 import 这些协议、绝不
import 实现（C1/C14）。P0 固定签名，实现体自 P1 起。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from questor.contracts.common import JsonObject
from questor.contracts.sandbox import SandboxDescriptor, SandboxPort
from questor.contracts.state_schema import Message
from questor.contracts.tool import ToolSpec


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    """一次模型调用的请求描述（消息 + 工具 + 采样设置）。"""

    model: str
    messages: tuple[Message, ...]
    tools: tuple[ToolSpec, ...] = ()
    system: str | None = None
    stream: bool = True
    settings: JsonObject | None = None


@dataclass(frozen=True, slots=True)
class StreamChunk:
    """一段归一化的流式增量；内核据此映射为 ``*_delta`` / tool_use / usage。"""

    kind: str  # text | reasoning | tool_call | usage | finish
    text: str | None = None
    tool_call: JsonObject | None = None
    usage: JsonObject | None = None
    finish_reason: str | None = None
    raw: Any | None = None


@runtime_checkable
class ProviderPort(Protocol):
    """模型访问端口。错误分类是纯函数（进 contracts），此处只产出归一化增量。"""

    async def stream(self, request: ProviderRequest):  # -> AsyncIterator[StreamChunk]
        """产出归一化 chunk；调用方负责按 ADR-0010 分类处置错误。"""
        ...


@runtime_checkable
class StorePort(Protocol):
    """append-only 事件日志 + 快照读写（design/01 §9；ADR-0005/0011/0020/0022）。

    唯一持久化路径；策略不持裸句柄（C4）。P3 起承载两类游标：per-run 逻辑 ``seq``
    （SSE ``after_seq`` 续传）与全局单调物理 ``gseq``（跨 run catch-up watermark，ADR-0011）。
    新方法是 **纯增量**（不改既有签名/信封/关联键，C6）；仅在 resume/发现路径被调用。
    """

    async def append(self, run_id: str, events: tuple[JsonObject, ...]) -> int: ...

    async def replay(
        self, run_id: str, after_seq: int, limit: int | None = None
    ) -> list[JsonObject]: ...

    async def sequence_head(self, run_id: str) -> int: ...

    async def save_checkpoint(self, checkpoint: JsonObject) -> None: ...

    async def latest_checkpoint(self, run_id: str) -> JsonObject | None: ...

    async def checkpoints(self, run_id: str, limit: int | None = None) -> list[JsonObject]:
        """该 run 的快照列表，**按 seq 新→旧**返回（供 ``rebuild_run`` 逐一尝试、回退到次近完好快照）。"""
        ...

    async def watermark(self) -> int:
        """当前全局物理序头部（无事件则 0）；跨 run catch-up 的水位基线。"""
        ...

    async def replay_global(
        self, after_watermark: int, limit: int | None = None
    ) -> list[JsonObject]:
        """跨 run 重放全局 ``gseq > after_watermark`` 的事件，按全局序返回（携 run_id/seq）。"""
        ...

    async def checkpoint_seq(self, run_id: str) -> int | None:
        """该 run 最近快照的 ``seq``（尾重放起点）；无快照返回 ``None``。"""
        ...

    async def list_unfinished_runs(self) -> tuple[str, ...]:
        """从 log 派生非终态 run id（有事件但无终态事件）；供 ``--resume`` 枚举。"""
        ...

    # ---- P9/ADR-0047：跨进程 exactly-once 的投递账本 + 单机多进程 run 租约（纯增量）----
    async def claim_delivery(self, delivery_id: str, ttl_seconds: float = 30.0) -> bool:
        """claim-then-deliver：拿到投递所有权返 True（首次 claim，或前次 claim 已过 TTL 的崩溃重取）。

        已 acked 或他人持有未过期 claim → False（防跨进程双投）。投递视图从事件重放重建，
        本表只是去重/认领账、不是第二事件真相（C13/C15）。"""
        ...

    async def delivery_state(self, delivery_id: str) -> str | None:
        """查询投递状态：None=未投、``"claimed"``=进行中、``"acked"``=已确认。"""
        ...

    async def ack_delivery(self, delivery_id: str) -> bool:
        """投递完成确认：置 acked（幂等；对未知/已 acked 返回当前是否处于 acked）。"""
        ...

    async def acquire_lease(self, run_id: str, holder: str, epoch: int, ttl_seconds: float) -> bool:
        """获取 run 驱动租约（单机多进程单写者）：无租约/已过期/同 holder 同 epoch → True 并盖章；
        他人未过期持有 → False。靠 SQLite ``BEGIN IMMEDIATE`` 串行化保证原子（跨进程有效）。"""
        ...

    async def renew_lease(self, run_id: str, holder: str, epoch: int) -> bool:
        """续租：仅当前 holder+epoch 匹配时刷新到期时间；否则 False（已被夺走）。"""
        ...

    async def release_lease(self, run_id: str, holder: str, epoch: int) -> bool:
        """释放租约：仅当前 holder+epoch 匹配时删除；否则 False。"""
        ...

    async def reclaim_expired_leases(self, now: float) -> int:
        """P10/ADR-0050：回收**已过期**的 run 租约行（瞬态派生视图，可安全重取）；返回删除数。

        只删 ``expires_at < now`` 的行（持有者可重取）。不碰未过期租约（单写者栅栏）。"""
        ...

    async def reclaim_stale_claims(self, now: float) -> int:
        """P10/ADR-0050：回收**超 TTL 未 ack** 的 in-flight claim 行（崩溃遗留、可安全重取）；返回删除数。

        只删 ``state='claimed'`` 且 ``claimed_at+ttl < now`` 的行。**绝不删已 acked 的投递行**
        （对抗评审 BLK-2：投递视图从 ``event_log`` 重建，ack 幂等键一删就 rebuild 重 claim→双投，
        破 exactly-once；acked 行的回收与 event_log 裁剪绑定后置）。"""
        ...

    # ---- B3：耐久提交队列（session 作用域；纯增量，不改既有 append/租约语义）----
    async def enqueue_submission(
        self,
        session_id: str,
        kind: str,
        payload: JsonObject,
        *,
        source: str,
        idem_key: str,
        digest: str,
        run_id: str | None = None,
    ) -> JsonObject:
        """入队一条提交：同 ``(session_id, idem_key)`` 同 digest → duplicate；异 digest → 冲突拒绝。

        返回 ``{item_id, change_version, duplicate}``（bounded）；在途数达 ``MAX_QUEUE_ITEMS`` 抛
        ``SubmissionQueueFullError``。多进程写者只在此表并发（各自 BEGIN IMMEDIATE + UNIQUE），
        ``event_log`` 仍只由持租约者 append。"""
        ...

    async def claim_submissions(self, session_id: str, *, limit: int = 100, run_id: str | None = None) -> list[JsonObject]:
        """原子 claim 该会话的 pending/deferred 行（置 deferred 并填 run_id）；按 seq_in_session 返回。"""
        ...

    async def ack_submissions(self, item_ids: tuple[str, ...]) -> int:
        """已应用命令置 consumed；返回受影响行数。"""
        ...

    async def release_submissions(self, item_ids: tuple[str, ...]) -> int:
        """未匹配/未应用的 claim 退回 pending（run_id 清空）；返回受影响行数。"""
        ...

    async def submissions_since(self, session_id: str, after_version: int, limit: int = 512) -> list[JsonObject]:
        """``change_version > after_version`` 的队列行（多端观察同一队；按 change_version 升序）。"""
        ...

    async def pending_submission_count(self, session_id: str) -> int:
        """该会话在途（pending + deferred）条数；入队背压判据。"""
        ...

    # ---- B4：会话作用域（sessions 表 + event_log.scope/session_id；不改 Envelope）----
    async def create_session(
        self,
        session_id: str | None = None,
        *,
        model: str | None = None,
        workspace_root: str | None = None,
        kind: str = "chat",
    ) -> str:
        """新建或幂等确保会话行；返回 session_id。"""
        ...

    async def ensure_session(self, session_id: str) -> JsonObject:
        """确保会话行存在并返回它。"""
        ...

    async def bind_run_session(self, run_id: str, session_id: str) -> None:
        """把 run 路由到 session（在 run_started 前绑定，事件列才不丢）。"""
        ...

    async def run_session(self, run_id: str) -> str | None:
        """该 run 的 session_id；未绑定返回 None。"""
        ...

    async def session_row(self, session_id: str) -> JsonObject | None:
        """会话行（含双游标/metadata）；无则 None。"""
        ...

    async def advance_last_consolidated(self, session_id: str, seq: int) -> int:
        """巩固游标只前进；返回受影响行数。"""
        ...

    async def set_history_start_seq(self, session_id: str, seq: int) -> int:
        """喂入起点只前进；返回受影响行数。"""
        ...

    async def session_events(self, session_id: str, limit: int | None = None) -> list[JsonObject]:
        """该会话事实流（含 scope/session_id 列）。"""
        ...

    async def session_transcript(self, session_id: str, limit: int = 8) -> list[JsonObject]:
        """最近 N 条 user/assistant 事实（新→旧），供 SeedContext 取原文。"""
        ...


@runtime_checkable
class Clock(Protocol):
    """时间端口：墙上时间 + 单调时钟（退避/超时须同基准，R08 B-P2）。"""

    def now(self) -> datetime: ...

    def monotonic(self) -> float: ...


class SurfacePort(Protocol):
    """传输面的**装配接缝**（OPT-2a）：组合根产出的 ``App.surface`` 只承诺调用方实际用到的方法。

    消费面（grep ``app.surface`` / ``EventServer(surface`` 的真实调用点）：
    ``interactive()`` → :meth:`run_once`；``__main__ --resume`` → :meth:`resume`；
    ``EventServer`` / ``SubagentOrchestrator`` → :meth:`_loop` / :meth:`_discover_mcp` /
    :meth:`_freeze_surface` / :meth:`_resolve_for_run`，并读写 :attr:`store`。

    为什么返回类型写 ``object``：contracts 是最内层（C1/C14），不得 import kernel/surfaces；
    ``_loop`` 实返 ``DefaultTurnLoop``、``_freeze_surface`` 实返 ``RunToolSurface``，具体类型由 L6
    实现提供，调用方按实现类型消费。

    为什么带下划线：这些方法本就是 surfaces 内部的装配件；本协议只把**既有调用面**显式化，
    不改名、不改签名（零行为变更）。刻意不加 ``@runtime_checkable``：协议含数据成员 ``store``，
    isinstance 校验既无需求也会退化成 hasattr 探测。
    """

    store: object

    async def run_once(self, text: str, *, on_delta: object | None = None) -> object: ...

    async def resume(self, run_id: str) -> object | None: ...

    def _resolve_for_run(self, run_id: str) -> tuple[object, object]: ...

    def _loop(
        self, bus: object, cancel: object, surface: object, subagent_spawner: object | None = None, *, run_id: str = "", session_id: str = ""
    ) -> object: ...

    async def _discover_mcp(self, run_id: str) -> tuple[list[object], object]: ...

    def _freeze_surface(self, run_id: str, extra_tools: list[object]) -> object: ...


class ContextAssemblerPort(Protocol):
    """上下文装配接缝（OPT-12a）：把 system prompt、skills catalog（及将来的记忆块）拼成一次请求的 system。

    契约：
    - 纯函数式、无 IO 副作用（只读目录）；**不得**在这里改任何权限/排序语义；
    - 默认实现（``surfaces._assembly.DefaultContextAssembler``）逐字节等于历史 surface 内联拼接，
      包括 ``system=None`` 时字面 ``"None"`` 进入 prompt 的现状——修它是 B7（OPT-12b），不在本刀；
    - 无技能目录时返回**入参原样**（``None`` 仍是 ``None``，不凭空造空串）。
    """

    def assemble(self, system: str | None, skills_dir: Path | None) -> str | None: ...


@runtime_checkable
class IdGenerator(Protocol):
    """id 生成端口（默认实现见 ``common.new_id``；测试可注入定序实现）。"""

    def new(self, prefix: str) -> str: ...


__all__ = [
    "ProviderRequest",
    "StreamChunk",
    "ProviderPort",
    "StorePort",
    "Clock",
    "IdGenerator",
    "SandboxDescriptor",
    "SandboxPort",
    "SurfacePort",
    "ContextAssemblerPort",
]
