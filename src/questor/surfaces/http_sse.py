"""L6 HTTP + SSE event service (ADR-0007). P0 = seam; behavior is P1 T10.

Transport binding (design/02 §4): ``data: {json}\\n\\n`` with a leading
``id: <seq>``; ``POST /run · /cancel · /resume``; reconnect carries
``Last-Event-ID``/``after_seq`` -> replay from the store. The SSE frame/headers
shape adapts CowAgent ``channel/web/api/openai_compat.py``; the ``id:<seq>`` +
after_seq replay wiring is written fresh (neither reference exposes it).

Surfaces import only contracts/state + the injected EventBus — never business
logic, never mutate state (S6/C14)."""

from __future__ import annotations

from abc import ABC, abstractmethod


class HttpSseSurface(ABC):
    @abstractmethod
    async def serve(self, host: str, port: int) -> None:
        """Expose the run/cancel/resume endpoints and the SSE stream."""
