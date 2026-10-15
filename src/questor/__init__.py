"""Questor — a from-scratch desktop general-purpose personal Agent Harness.

Layer map (L0 innermost → L6 outermost; dependencies point inward only):

- :mod:`questor.contracts`   L0 shared vocabulary (schemas, events, Ports)
- :mod:`questor.state`       L1 Domain_State + reduce
- :mod:`questor.kernel`      L2 Harness runtime (loop, bus, permissions)
- :mod:`questor.capabilities` L3 tools / skills / mcp
- :mod:`questor.policy`      L4 pluggable Agent strategies (PolicyPort)
- :mod:`questor.providers`   L5 port adapters (LiteLLM, SQLite, clock, id)
- :mod:`questor.surfaces`    L6 transports (CLI, HTTP+SSE) — zero business logic

P0 delivers the compilable interface skeleton (stub signatures + layering
guards); behavior lands from P1. See ``docs/plan/00-design-skeleton.md``.
"""

from questor.version import __version__

__all__ = ["__version__"]
