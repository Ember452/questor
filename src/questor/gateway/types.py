"""Gateway value types shared by the runtime pool and its helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GatewayStreamUpdate:
    """One outbound update produced while processing a channel message."""

    kind: str
    text: str
    metadata: dict[str, object]
    media: list[str] | None = None

# questor: allow R3 -- until W9 rename wave
