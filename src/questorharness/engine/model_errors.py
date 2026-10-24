"""Provider error classification and per-request token limits."""

from __future__ import annotations

import re

from questorharness.contracts.errors import is_prompt_too_long_error

MAX_SAFE_COMPLETION_TOKENS = 128_000

# 单一定义处在 contracts.errors;引擎侧保留下划线名,query.py 与测试都从
# 本模块取它,分类口径不变。
_is_prompt_too_long_error = is_prompt_too_long_error


def _bounded_completion_tokens(max_tokens: int, context_window_tokens: int | None = None) -> int:
    """Return a conservative per-request output token cap.

    Some OpenAI-compatible providers reject very large ``max_tokens`` before
    the request reaches model-side context management.  Keep oversized user
    config from making every turn fail while preserving normal defaults.
    """
    limit = MAX_SAFE_COMPLETION_TOKENS
    if context_window_tokens is not None and context_window_tokens > 0:
        limit = min(limit, int(context_window_tokens))
    return max(1, min(int(max_tokens), limit))


def _extract_completion_token_limit(exc: Exception) -> int | None:
    """Parse provider errors such as "supports at most 128000 completion tokens"."""
    text = str(exc).lower().replace(",", "")
    patterns = (
        r"supports at most\s+(\d+)\s+completion tokens",
        r"at most\s+(\d+)\s+completion tokens",
        r"max(?:imum)?(?:_completion)?[_\s-]tokens.*?(?:<=|less than or equal to|at most)\s+(\d+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                return max(1, int(match.group(1)))
            except ValueError:
                return None
    return None


def _is_completion_token_limit_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        ("max_tokens" in text or "max_completion_tokens" in text)
        and ("too large" in text or "at most" in text or "completion tokens" in text)
    )


class MaxTurnsExceeded(RuntimeError):
    """Raised when the agent exceeds the configured max_turns for one user prompt."""

    def __init__(self, max_turns: int) -> None:
        super().__init__(f"Exceeded maximum turn limit ({max_turns})")
        self.max_turns = max_turns

# questor: allow R7 -- until W8 adds the mirror test
