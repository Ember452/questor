"""L1 状态迁移咽喉 ``apply()``（v3 §4.1；HARD C2/C5/C7/C13）。

``reduce`` 是纯状态机，但"什么时候允许调它、同一条命令重复投递怎么办"过去散在 kernel 的
17 个调用点里（loop 16 + recovery 1）。本模块把这件事收成**唯一入口**：

    幂等判定 → reduce（纯） → 返回 (新 Run, 事件)

- 幂等作用域 = **一条 run 血统**（``run_id`` + ``created_at``）：同一 ``idempotency_key``
  指向同一 digest 且状态已推进到该次应用之后 → no-op（不重复产事件）；同 key 异 digest
  且状态未推进 → :class:`IdempotencyConflictError`（拒，绝不"后者覆盖前者"）。
- **无 IO**：``store`` 由调用方注入，仅为将来的 durable command window（§4.3，属 B6/B7）
  留接口；B0 的命令窗口是进程内的，``apply`` 自己既不读写库、也不发事件。
- 事件只**返回**不发送：emit 仍由 kernel 的 bus 负责（C5：事件是投影，不是状态输入）。

血统用 ``created_at`` 而不是 ``id(run)``：``reduce`` 每次返回新实例，实例身份会变；而
``created_at`` 在 ``replace`` 链上原样保留、跨快照 round-trip 也稳定——正是"同一条 run"的
最小可用身份。反过来，两个测试用同一 ``run_id`` 建 run 会得到不同 ``created_at``，互不污染。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from questor.contracts.events import Command, Envelope
from questor.contracts.ports import StorePort
from questor.state.domain_state import Run
from questor.state.reduce import reduce

#: 进程内命令窗口上限：只是防长驻 sidecar 无界增长；溢出不改变语义（窗口是优化，不是真相）。
_WINDOW_MAX = 4096


class IdempotencyConflictError(ValueError):
    """同一个 ``idempotency_key`` 在同一状态上指向了不同命令：拒绝，绝不静默覆盖。"""


@dataclass(frozen=True, slots=True)
class _WindowEntry:
    """一条已应用命令的指纹与"应用后状态"的游标（用于判断该状态是否已含这次应用）。"""

    digest: str
    seq_after: int
    source: str


#: 进程内命令窗口：``(血统, idempotency_key) -> _WindowEntry``。
#: 单事件循环内同步访问（apply 不 await），故不加锁；跨进程的耐久窗口属 B6/B7。
_WINDOW: dict[tuple[str, str], _WindowEntry] = {}


def reset_idempotency_window() -> None:
    """清空进程内命令窗口（仅测试/诊断用；生产不需要也不应调用）。"""
    _WINDOW.clear()


def _lineage(run: Run) -> str:
    """一条 run 血统的身份：``run_id`` + 创建时间（reduce 链上不变、跨快照稳定）。"""
    return f"{run.run_id}@{run.created_at.isoformat()}"


def _digest(command: Command) -> str:
    """命令内容指纹：同 key 是否指向同一意图（与 RunController 的 ``repr`` 口径一致）。"""
    return hashlib.sha256(repr(command).encode("utf-8")).hexdigest()


def apply(
    store: StorePort | None,
    run: Run,
    command: Command,
    *,
    source: str,
    idempotency_key: str,
    now: datetime | None = None,
) -> tuple[Run, tuple[Envelope, ...]]:
    """唯一 reduce 入口：幂等判定 → reduce → 返回 ``(Run, 事件元组)``。

    ``source`` 只用于审计/冲突报错（谁提的）；``now`` 透传给 reduce 保证确定性。
    ``store`` 是注入位，本函数不做任何 IO（见模块 docstring）。
    """
    if not idempotency_key:
        raise ValueError("apply() requires a non-empty idempotency_key (idempotency is the chokepoint contract)")
    _ = store  # B0：仅注入位（durable command_window 属 B6/B7）；本函数不做 IO。

    lineage = _lineage(run)
    key = (lineage, idempotency_key)
    digest = _digest(command)
    entry = _WINDOW.get(key)
    if entry is not None:
        if entry.digest != digest:
            if entry.seq_after == run.seq:
                raise IdempotencyConflictError(
                    f"idempotency key {idempotency_key!r} from {source!r} is already bound to a different "
                    f"{command.type} command on run {run.run_id}; refusing to overwrite (no last-writer-wins)"
                )
            # 状态已前进/已被快照重建：同 key 在新状态上指向新意图，如实记录（不误判为重复）。
        elif entry.seq_after == run.seq:
            # 同 key 同 digest 且状态已含这次应用 → 幂等 no-op：不重复产事件。
            return run, ()

    new_run, events = reduce(run, command, now=now)
    _remember(key, digest, new_run.seq, source)
    if new_run.status.is_terminal:
        _evict_lineage(lineage, keep=key)
    return new_run, tuple(events)


def _remember(key: tuple[str, str], digest: str, seq_after: int, source: str) -> None:
    _WINDOW[key] = _WindowEntry(digest=digest, seq_after=seq_after, source=source)
    if len(_WINDOW) > _WINDOW_MAX:
        for stale in list(_WINDOW)[: len(_WINDOW) - _WINDOW_MAX]:
            del _WINDOW[stale]


def _evict_lineage(lineage: str, *, keep: tuple[str, str]) -> None:
    """终态后回收该血统的窗口条目（保留终态那一条，防同一条终态被重复投递时重复 reduce）。"""
    for stale in [k for k in _WINDOW if k[0] == lineage and k != keep]:
        del _WINDOW[stale]


__all__ = ["IdempotencyConflictError", "apply", "reset_idempotency_window"]
