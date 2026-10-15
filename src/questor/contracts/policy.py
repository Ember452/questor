"""L4 Policy contract (design/05; R01 G-6 loopdriver). P0 fixes the interface.

Ownership (05 §0): a strategy owns prompts / tool allow-list / algorithm, and does
**NOT** own model routing, approval/denylist, sandbox, or persistence writes. It
reads a :class:`PolicyView` and returns a single, untrusted :class:`PolicyIntent`.
Pure data => naturally serializable, but **no RPC in v1** (C12).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Protocol

from questor.contracts.common import JsonObject
from questor.contracts.state_schema import Budget, Message, ToolCall
from questor.contracts.tool import ToolSpec


@dataclass(frozen=True, slots=True)
class PolicyView:
    """The ONLY thing a strategy may read: a read-only, field-projected snapshot.

    Never exposes checkpoints / permission ctx / LoopState / internal metadata
    (C2/C3). Structure-shared (COW), not a per-turn deep copy."""

    context: tuple[Message, ...] = ()
    task_tree: tuple[JsonObject, ...] = ()  # node projections (shape draft)
    tool_results: tuple[ToolCall, ...] = ()
    tools: tuple[ToolSpec, ...] = ()
    budget: Budget = field(default_factory=Budget)


@dataclass(frozen=True, slots=True)
class ProposeToolCall:
    name: str
    args: JsonObject
    node_id: str | None = None
    type: ClassVar[str] = "propose_tool_call"


@dataclass(frozen=True, slots=True)
class ProposePlanUpdate:
    ops: tuple[JsonObject, ...]
    type: ClassVar[str] = "propose_plan_update"


@dataclass(frozen=True, slots=True)
class AdviseCompact:
    """Advisory only — the kernel decides (design/01 I2)."""

    pressure: float
    type: ClassVar[str] = "advise_compact"


@dataclass(frozen=True, slots=True)
class SuggestFinish:
    final_text: str | None = None
    type: ClassVar[str] = "suggest_finish"


@dataclass(frozen=True, slots=True)
class SuggestCancel:
    reason: str
    type: ClassVar[str] = "suggest_cancel"


#: Strategy output is untrusted input; the kernel validates before acting (L1).
PolicyIntent = ProposeToolCall | ProposePlanUpdate | AdviseCompact | SuggestFinish | SuggestCancel


@dataclass(frozen=True, slots=True)
class LoopPolicy:
    """Kernel-facing per-run policy knobs (wuu loopdriver, R01 G-6)."""

    max_turns: int = 25
    disable_tools: bool = False
    disable_compaction: bool = True  # compaction not exercised until P10


class PolicyPort(Protocol):
    """A pluggable Agent strategy. No execute/sandbox/store-write handle here.

    P1 strategies (e.g. the in-process ReAct policy) subclass this Protocol
    explicitly for nominal typing. ``id``/``fingerprint`` are per-strategy data."""

    id: str
    fingerprint: str

    def init(self) -> None: ...

    def propose_action(self, view: PolicyView) -> PolicyIntent: ...

    def on_tool_result(self, result: ToolCall) -> None: ...

    def dispose(self) -> None: ...


__all__ = [
    "PolicyView",
    "ProposeToolCall",
    "ProposePlanUpdate",
    "AdviseCompact",
    "SuggestFinish",
    "SuggestCancel",
    "PolicyIntent",
    "LoopPolicy",
    "PolicyPort",
]
