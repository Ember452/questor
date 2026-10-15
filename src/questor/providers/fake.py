"""A deterministic ``ProviderPort`` double for tests and the offline CLI demo.

Replays a scripted list of "turns", where each turn is the sequence of
``StreamChunk``\\ s the model would emit. No network, no key — it lets the loop's
DoD (happy path + cancel + deny + illegal-intent) be verified repeatably.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import ClassVar

from questor.contracts.ports import ProviderPort, ProviderRequest, StreamChunk


class ScriptedProvider(ProviderPort):
    turns: list[list[StreamChunk]]
    _index: int

    def __init__(self, turns: list[list[StreamChunk]]) -> None:
        self.turns = turns
        self._index = 0

    async def stream(self, request: ProviderRequest) -> AsyncIterator[StreamChunk]:
        if self._index >= len(self.turns):  # script exhausted -> politely stop
            yield StreamChunk(kind="finish", finish_reason="stop")
            return
        for chunk in self.turns[self._index]:
            yield chunk
        self._index += 1


class EchoProvider(ProviderPort):
    """Minimal provider that just streams a canned answer, no tools (smoke demo)."""

    answer: ClassVar[str] = "echo: got your message."

    async def stream(self, request: ProviderRequest) -> AsyncIterator[StreamChunk]:
        for token in self.answer.split(" "):
            yield StreamChunk(kind="text", text=token + " ")
        yield StreamChunk(kind="finish", finish_reason="stop")
