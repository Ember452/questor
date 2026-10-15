"""L1 Domain/State — the single authoritative, immutable, replayable state.

Pure data models + invariants; ``reduce`` (the only writer) lives here from P1.
Depends only on :mod:`questor.contracts` (C2)."""
