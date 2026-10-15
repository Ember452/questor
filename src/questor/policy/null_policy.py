"""L4 policy stub — the minimal ``PolicyPort`` placeholder (design/05).

P1 T11 replaces this with the in-process ReAct strategy. ``propose_action``
returns a single untrusted intent; the kernel validates before acting (L1 in
design/04). Registered/discovery/AB are P9; only ``id``/``fingerprint`` are here.
"""

from __future__ import annotations

from questor.contracts.policy import PolicyIntent, PolicyPort, PolicyView


class NullPolicy(PolicyPort):
    id = "null"
    fingerprint = "null:0"

    def propose_action(self, view: PolicyView) -> PolicyIntent:
        raise NotImplementedError("ReAct strategy lands in P1 (T11)")


__all__ = ["NullPolicy"]
