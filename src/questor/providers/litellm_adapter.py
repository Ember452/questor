"""L5 ProviderPort adapter → LiteLLM (ADR-0002). P0 = class seam, no SDK import.

The streaming assembly (chunk tool-arg accumulation, `include_usage` tail,
reasoning/text separation) is P1 T4, adapted from crewAI ``llm.py``. `litellm`
is imported there (only this module may use it — ruff banned-api exempts
``providers/*``)."""

from __future__ import annotations

from questor.contracts.ports import ProviderPort, ProviderRequest, StreamChunk


class LiteLLMProvider(ProviderPort):
    def __init__(self, model: str) -> None:
        self.model = model

    async def stream(self, request: ProviderRequest):  # -> AsyncIterator[StreamChunk]
        raise NotImplementedError("LiteLLM streaming adapter lands in P1 (T4)")


__all__ = ["LiteLLMProvider", "StreamChunk"]
