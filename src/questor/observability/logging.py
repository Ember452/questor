"""横切可观测性（STRUCTURE S7；HARD C14；ROADMAP §1.5 从 P1 就落轻量面）。

只读：观测事件、把终态错误归一化为结构化日志。只依赖 ``contracts``——绝不 import
kernel/policy 实现、绝不改状态（S7）。完整的 tracing/metrics/trace 视图归 P10；P1 只需
结构化日志 + 终态错误面，以做到“错误从第一天起就可见”。
"""

from __future__ import annotations

import logging

from questor.contracts.events import Envelope, EventType

_LOG = logging.getLogger("questor")

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
    """为 CLI/sidecar 进程配置 basicConfig（幂等）。"""
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=False)


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
