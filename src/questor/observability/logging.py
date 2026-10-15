"""Cross-cutting observability (STRUCTURE S7; HARD C14; ROADMAP §1.5 lightweight-from-P1).

Read-only: observes events and logs a normalized error stack. Depends only on
``contracts`` — never imports kernel/policy implementations and never mutates
state (S7). Full tracing/metrics/trace-viewer are P10; P1 only needs structured
logs + the terminal-event error surface to satisfy "errors visible from day 1".
"""

from __future__ import annotations

import logging

from questor.contracts.events import Envelope, EventType

_LOG = logging.getLogger("questor")

# Levels for the event stream; error-class events never fall silent (C6).
_LEVELS: dict[str, int] = {
    EventType.RUN_FAILED: logging.ERROR,
    EventType.WARNING: logging.WARNING,
    EventType.RESYNC_REQUIRED: logging.WARNING,
    EventType.RUN_CANCELLED: logging.INFO,
    EventType.RUN_COMPLETED: logging.INFO,
    EventType.RUN_STARTED: logging.INFO,
}


def configure_logging(level: int = logging.INFO) -> None:
    """Idempotent basicConfig for the CLI/sidecar process."""
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=False)


def log_event(env: Envelope) -> None:
    """One structured line per (durable) event; deltas are skipped to avoid spam."""
    if env.type in {EventType.TEXT_DELTA, EventType.REASONING_DELTA, EventType.HEARTBEAT, EventType.TOOL_PROGRESS}:
        return
    level = _LEVELS.get(env.type, logging.DEBUG)
    summary = env.data.get("error") or env.data.get("status") or env.data.get("message") or ""
    _LOG.log(level, "[%s] run=%s turn=%s seq=%s %s", env.type, env.run_id, env.turn, env.seq, summary)


def error_from_failed_event(env: Envelope) -> str | None:
    """Extract a human-readable error line from a ``run_failed`` event payload."""
    if env.type != EventType.RUN_FAILED:
        return None
    err = env.data.get("error") or {}
    return f"{err.get('code', 'error')}: {err.get('message', '')}".strip(": ")
