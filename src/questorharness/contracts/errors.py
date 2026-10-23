"""Cross-layer error types.

These classes live in ``contracts`` so that both capabilities and providers can
refer to the same exception objects without capabilities importing providers.
"""

from __future__ import annotations


class SandboxUnavailableError(RuntimeError):
    """Raised when sandboxing is required but unavailable."""


class McpServerNotConnectedError(Exception):
    """Raised when an MCP server is not connected or its session has been lost."""

# questor: allow R7 -- until W8 adds the mirror test
