"""Hooks exports."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from questorharness.contracts.hooks import AggregatedHookResult, HookEvent, HookResult
    from questorharness.runtime.hooks.executor import HookExecutionContext, HookExecutor
    from questorharness.runtime.hooks.loader import HookRegistry

__all__ = [
    "AggregatedHookResult",
    "HookEvent",
    "HookExecutionContext",
    "HookExecutor",
    "HookRegistry",
    "HookResult",
    "load_hook_registry",
]


def __getattr__(name: str):
    if name == "HookEvent":
        from questorharness.contracts.hooks import HookEvent

        return HookEvent
    if name in {"HookExecutionContext", "HookExecutor"}:
        from questorharness.runtime.hooks.executor import HookExecutionContext, HookExecutor

        return {
            "HookExecutionContext": HookExecutionContext,
            "HookExecutor": HookExecutor,
        }[name]
    if name in {"HookRegistry", "load_hook_registry"}:
        from questorharness.runtime.hooks.loader import HookRegistry, load_hook_registry

        return {
            "HookRegistry": HookRegistry,
            "load_hook_registry": load_hook_registry,
        }[name]
    if name in {"AggregatedHookResult", "HookResult"}:
        from questorharness.contracts.hooks import AggregatedHookResult, HookResult

        return {
            "AggregatedHookResult": AggregatedHookResult,
            "HookResult": HookResult,
        }[name]
    raise AttributeError(name)

# questor: allow R4 -- until W8 facade split
