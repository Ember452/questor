"""Cross-layer error types.

These classes live in ``contracts`` so that both capabilities and providers can
refer to the same exception objects without capabilities importing providers.
The provider-error needle table lives here for the same reason: the engine's
reactive-compaction retry and the compactor's internal retry must classify the
same provider strings, and two copies of the table would drift apart.
"""

from __future__ import annotations


class SandboxUnavailableError(RuntimeError):
    """Raised when sandboxing is required but unavailable."""


class McpServerNotConnectedError(Exception):
    """Raised when an MCP server is not connected or its session has been lost."""


# Substrings provider APIs put into "the prompt does not fit the context
# window" errors. Order and wording are load-bearing: behaviour tests pin
# representative providers, so additions need a red case first.
PROMPT_TOO_LONG_ERROR_NEEDLES: tuple[str, ...] = (
    "prompt too long",
    "context_length_exceeded",
    "context length",
    "maximum context",
    "context window",
    "input tokens exceed",
    "messages resulted in",
    "reduce the length of the messages",
    "configured limit",
    "too many tokens",
    "too large for the model",
    "maximum context length",
    "exceed_context",
    "exceeds the available context size",
    "available context size",
)


def is_prompt_too_long_error(exc: Exception) -> bool:
    """Return True when *exc* looks like a prompt-exceeds-context error."""
    text = str(exc).lower()
    return any(needle in text for needle in PROMPT_TOO_LONG_ERROR_NEEDLES)

# questor: allow R7 -- until W8 adds the mirror test
