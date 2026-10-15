"""L2 recovery — rebuild a Run from its latest checkpoint (A1; ADR-0005).

Recovery = load the most recent turn-boundary snapshot (the authoritative,
pairing-consistent restore point written by the loop) and reconstruct the
``Domain_State``. P1 checkpoints at every turn boundary so a restart resumes from
the last completed turn; ``parallel`` is off so there is no multi-pending rehydration.
"""

from __future__ import annotations

import json

from questor.contracts.ports import StorePort
from questor.state.domain_state import Run
from questor.state.snapshot import from_snapshot


async def resume_run(store: StorePort, run_id: str) -> Run | None:
    """Return the Run as of its latest checkpoint, or ``None`` if none exists."""
    checkpoint = await store.latest_checkpoint(run_id)
    if checkpoint is None:
        return None
    return from_snapshot(json.loads(checkpoint["state_digest"]))
