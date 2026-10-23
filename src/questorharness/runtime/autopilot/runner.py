"""Runtime runner wiring for autopilot turns.

The runner is injected by ``bootstrap`` so this package never imports the
composition root. Keeping the slot in its own module lets the verification
mixin read it without importing the store.
"""

from __future__ import annotations

from typing import Awaitable, Callable

RuntimeRunner = Callable[..., Awaitable[str]]

_RUNTIME_RUNNER: RuntimeRunner | None = None


def configure_runtime_runner(runner: RuntimeRunner) -> None:
    """Register the callable that runs one agent turn."""
    global _RUNTIME_RUNNER
    _RUNTIME_RUNNER = runner


def get_runtime_runner() -> RuntimeRunner | None:
    """Return the configured runner, or ``None`` when bootstrap has not wired one."""
    return _RUNTIME_RUNNER

# questor: allow R7 -- until W8 adds the mirror test
