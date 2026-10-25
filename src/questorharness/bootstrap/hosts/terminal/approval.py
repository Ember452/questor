"""审批/提问的时限语义：服务端 fail-closed，客户端也必须说清楚还剩多久。

`authority` 的默认超时是 300 秒，超时即 deny / 空答案。终端不做倒计时动画，
但必须给出**截止提示**并在本地同样超时放弃等待——否则用户会对着一个永远不动
的提示敲回车，而服务端早已按拒绝处理。
"""

from __future__ import annotations

import time

DEFAULT_TIMEOUT_SECONDS = 300.0


def deadline_hint(timeout: float, *, kind: str = "审批") -> str:
    """给用户看的一句截止说明（含 fail-closed 方向）。"""

    seconds = int(timeout)
    if kind == "提问":
        return f"  {seconds} 秒内未回答视为未回答（超时不阻塞回合）"
    return f"  {seconds} 秒内未回答将自动拒绝（fail-closed）"


def remaining(deadline: float, *, now: float | None = None) -> int:
    """距截止还剩多少秒（不小于 0）。"""

    return max(0, int(deadline - (now if now is not None else time.monotonic())))


def deadline_from(timeout: float, *, now: float | None = None) -> float:
    """由超时秒数算出单调时钟截止点。"""

    return (now if now is not None else time.monotonic()) + timeout
