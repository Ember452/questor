"""API error types for QuestorHarness."""

from __future__ import annotations


class QuestorHarnessApiError(RuntimeError):
    """Base class for upstream API failures."""


class AuthenticationFailure(QuestorHarnessApiError):
    """Raised when the upstream service rejects the provided credentials."""


class RateLimitFailure(QuestorHarnessApiError):
    """Raised when the upstream service rejects the request due to rate limits."""


class RequestFailure(QuestorHarnessApiError):
    """Raised for generic request or transport failures."""
