"""L2 turn loop (design/04). P0 = the abstract seam; the phase pipeline is P1 T7.

The kernel drives the loop, asks ``PolicyPort`` for one intent per turn, then
validates/executes/accounts. It is *pure mechanism*: it never imports a concrete
policy/surface (they are injected; C1/C14) and never talks to a model directly."""

from __future__ import annotations

from abc import ABC, abstractmethod

from questor.contracts.events import Command


class TurnLoop(ABC):
    """Drives one Run from ``SubmitMessage`` to a single terminal event (C7)."""

    @abstractmethod
    async def run(self, command: Command) -> None:
        """Apply the command, loop turns, emit events. Implemented in P1."""
