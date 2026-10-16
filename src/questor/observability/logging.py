"""横切可观测性（STRUCTURE S7；HARD C14；ROADMAP §1.5 从 P1 就落轻量面）。

只读：观测事件、把终态错误归一化为结构化日志。只依赖 ``contracts``——绝不 import
kernel/policy 实现、绝不改状态（S7）。完整的 tracing/metrics/trace 视图归 P10；P1 只需
结构化日志 + 终态错误面，以做到“错误从第一天起就可见”。
"""

from __future__ import annotations

import logging
import sys

from questor.contracts.events import Envelope, EventType

_LOG = logging.getLogger("questor")

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

# 各类事件的日志级别；错误类事件绝不静默（C6）。
_LEVELS: dict[str, int] = {
    EventType.RUN_FAILED: logging.ERROR,
    EventType.WARNING: logging.WARNING,
    EventType.RESYNC_REQUIRED: logging.WARNING,
    EventType.RUN_CANCELLED: logging.INFO,
    EventType.RUN_COMPLETED: logging.INFO,
    EventType.RUN_STARTED: logging.INFO,
}


def configure_logging(level: int = logging.INFO) -> None:
    """装配 console sink：显式绑 **stderr**（不依赖 basicConfig 默认），幂等不叠 handler。

    组合根唯一调用（DESIGN §11）；重复调用只调级别、不再新增 handler（DoD A④）。机器可读的
    stdout 永不写日志（DoD A③）。
    """
    root = logging.getLogger()
    existing = [h for h in root.handlers if isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) is sys.stderr]
    if existing:
        for h in existing:
            h.setLevel(level)
        root.setLevel(level)
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT))
    handler.setLevel(level)
    root.addHandler(handler)
    root.setLevel(level)


def log_event(env: Envelope) -> None:
    """每条（可持久）事件打一行；delta 跳过以防刷屏。"""
    if env.type in {EventType.TEXT_DELTA, EventType.REASONING_DELTA, EventType.HEARTBEAT, EventType.TOOL_PROGRESS}:
        return
    level = _LEVELS.get(env.type, logging.DEBUG)
    summary = env.data.get("error") or env.data.get("status") or env.data.get("message") or ""
    _LOG.log(level, "[%s] run=%s turn=%s seq=%s %s", env.type, env.run_id, env.turn, env.seq, summary)


def error_from_failed_event(env: Envelope) -> str | None:
    """从 ``run_failed`` 事件载荷里抽一行人类可读错误；非该类型返回 None。"""
    if env.type != EventType.RUN_FAILED:
        return None
    err = env.data.get("error") or {}
    return f"{err.get('code', 'error')}: {err.get('message', '')}".strip(": ")
