"""L6 CLI surface — the P1 DoD main stage ("ask one line, stream one answer").

Zero business logic (STRUCTURE S6): reads user input -> ``SubmitMessage``,
renders the event stream, maps Ctrl-C to a ``Cancel`` Command, and delegates
``ask`` to a terminal approver (adapted from DeepCode ``harness/approval.py``).
Behavior lands in P1 T10."""

from __future__ import annotations

from abc import ABC, abstractmethod


class CliSurface(ABC):
    @abstractmethod
    async def run(self) -> int:
        """Start an interactive run and stream events until terminal/cancel."""
