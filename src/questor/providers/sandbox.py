"""L5 SandboxPort — the "none" backend (design/03 §4; HARD C9/T4).

A null backend fences *nothing*, so the Harness must fail-closed: `exec`/high
risk tools are denied rather than run raw. Real backends (seatbelt/bubblewrap/
Windows job) land from P2. P0 just ships the probe shape + the honest False."""

from __future__ import annotations

from questor.contracts.ports import SandboxPort


class NullSandbox(SandboxPort):
    def fences_writes(self) -> bool:
        return False

    def fences_network(self) -> bool:
        return False

    def isolates_process_tree(self) -> bool:
        return False

    def wrap_argv(self, capability: str, argv: tuple[str, ...]) -> tuple[str, ...]:
        raise NotImplementedError("sandbox wrapping lands in P2")


__all__ = ["NullSandbox"]
