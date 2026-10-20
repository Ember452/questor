"""L2 会话形状操作（B13）：回退 / 分叉 / 会话元数据都经唯一咽喉落事实，**旧流不改写**。

三条判据逐条对上 §13 B13：

- **rewind 后事实流不变**：只在**新 run** 上落一条 durable `run_rewounded` 并把
  `history_base={run_id, to_seq}` 写进新 run 的权威状态；旧 run 的事件行一条都不动。
  旧前缀靠 B4 已有的 seed 接缝带进来（`prefix_seed_refs`），**不新造第二条历史通道**。
- **fork 带 `history_base` 锚**：新会话流上落 `session_forked`（源会话 id + 分叉位点），源流不动。
- **不开第二张会话表**：会话行仍只有 `sessions`（title/archived/pinned 是既有列）；元数据变更
  同时落 durable 事件，使"会话列表"原则上可由 `sess:<id>` 流重建，而不是只能读表（C13）。

会话作用域流的 id 形状是 `sess:<session_id>`——与 B9 的 `TurnSettler` **同一个约定**，
不在这里重新发明（两处各拼一次字符串迟早会分叉）。
"""

from __future__ import annotations

import logging

from questor.contracts.events import Envelope, ForkSession, RewindRun, UpdateSession
from questor.kernel.seed import SeedRef
from questor.state.domain_state import Run
from questor.state.transition import apply

_LOG = logging.getLogger("questor.session_ops")

#: 会话作用域流的 id 前缀（与 `kernel/settle.py`、`surfaces/cli.py` 同一形状）。
SESSION_STREAM_PREFIX = "sess:"


def session_stream_id(session_id: str) -> str:
    """会话作用域流的 run id：`sess:<session_id>`。"""
    return f"{SESSION_STREAM_PREFIX}{session_id}"


async def apply_on_stream(
    store: object | None,
    bus: object | None,
    *,
    stream_run_id: str,
    command: object,
    source: str = "session_ops",
    idempotency_key: str,
) -> tuple[Run, tuple[Envelope, ...]]:
    """在给定流上经唯一咽喉 `apply()` 落一条命令，并把产出的事件交给总线持久化。

    游标从 store 的 `sequence_head` 起（会话流没有活 controller，这是唯一安全的取号方式）；
    无 store / 无总线时退化为纯 reduce + 返回事件（测试与离线路径用，不静默丢事件）。
    """
    head = 0
    if store is not None and callable(getattr(store, "sequence_head", None)):
        head = int(await store.sequence_head(stream_run_id))  # type: ignore[union-attr]
    run = Run(run_id=stream_run_id, seq=head)
    applied = apply(store, run, command, source=source, idempotency_key=idempotency_key)  # type: ignore[arg-type]
    new_run, events = applied
    if bus is not None:
        for env in events:
            await bus.emit(env)  # type: ignore[union-attr]
    return new_run, tuple(events)


async def apply_session_update(
    store: object | None,
    bus: object | None,
    *,
    session_id: str,
    title: str | None = None,
    archived: bool | None = None,
    pinned: bool | None = None,
    idempotency_key: str | None = None,
) -> tuple[Run, tuple[Envelope, ...]]:
    """改名 / 归档 / 置顶：**先与行的现值比对**，只对本次真变化者发事件并发投影写。

    为什么比对而不是只靠幂等键：会话流没有活 controller，每次 `apply_on_stream` 都从 store 头
    重新取号，所以"同一个值再 PATCH 一次"在事件层面会被当成新事实。重试/双击/前端重放都不该
    把"改名为 X"记成两次——**只有真的变了才是事实**。行写放在事件之后：事实是唯一权威（C13），
    投影写失败时事件仍在，行可由事件重刷。
    """
    current: dict[str, object] = {}
    if store is not None and callable(getattr(store, "session_row", None)):
        row = await store.session_row(session_id)  # type: ignore[union-attr]
        current = dict(row or {})
    wanted = {"title": title, "archived": archived, "pinned": pinned}
    changed = {name: value for name, value in wanted.items() if value is not None and current.get(name) != value}
    stream = session_stream_id(session_id)
    if not changed:
        head = 0
        if store is not None and callable(getattr(store, "sequence_head", None)):
            head = int(await store.sequence_head(stream))  # type: ignore[union-attr]
        return Run(run_id=stream, seq=head), ()
    key = idempotency_key or f"session:{session_id}:" + ":".join(f"{name}={changed[name]}" for name in sorted(changed))
    command = UpdateSession(
        run_id=stream,
        session_id=session_id,
        title=changed.get("title"),
        archived=changed.get("archived"),
        pinned=changed.get("pinned"),
    )
    new_run, events = await apply_on_stream(store, bus, stream_run_id=stream, command=command, source="session", idempotency_key=key)
    if store is not None and callable(getattr(store, "update_session_row", None)):
        await store.update_session_row(session_id, **changed)  # type: ignore[union-attr]
    return new_run, events


async def apply_fork(
    store: object | None,
    bus: object | None,
    *,
    new_session_id: str,
    source_session_id: str,
    from_seq: int,
    reason: str | None = None,
) -> tuple[Run, tuple[Envelope, ...]]:
    """分叉：事实落在**新会话**的流上，源会话流一条不改。"""
    stream = session_stream_id(new_session_id)
    command = ForkSession(
        run_id=stream,
        source_session_id=source_session_id,
        from_seq=from_seq,
        reason=reason,
    )
    return await apply_on_stream(
        store, bus, stream_run_id=stream, command=command, source="session", idempotency_key=f"fork:{new_session_id}"
    )


def make_rewind(*, new_run_id: str, base_run_id: str, base_to_seq: int, reason: str | None = None) -> RewindRun:
    """构造回退命令（新 run 自己带上"我从哪儿来"的锚）。"""
    return RewindRun(run_id=new_run_id, base_run_id=base_run_id, base_to_seq=base_to_seq, reason=reason)


async def prefix_seed_refs(store: object | None, *, base_run_id: str, base_to_seq: int, session_id: str) -> tuple[SeedRef, ...]:
    """把旧 run 的前缀（``seq <= base_to_seq``）映成 B4 seed 用的**全局 gseq** 引用。

    seed 接缝只认 gseq（跨 run 唯一），而 rewind 的位点是 per-run seq——这里做唯一的换算，
    不让 surface 自己去猜两个游标的关系。
    """
    if store is None or not callable(getattr(store, "replay", None)):
        return ()
    rows = await store.replay(base_run_id, 0)  # type: ignore[union-attr]
    return tuple(SeedRef(session_id, int(row["gseq"])) for row in rows if int(row["seq"]) <= base_to_seq)


__all__ = [
    "SESSION_STREAM_PREFIX",
    "apply_fork",
    "apply_on_stream",
    "apply_session_update",
    "make_rewind",
    "prefix_seed_refs",
    "session_stream_id",
]
