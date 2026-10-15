"""L4 in-process ReAct strategy implementing ``PolicyPort`` (design/05; P1 T11).

Reads the read-only ``PolicyView`` and returns exactly one untrusted intent per
turn: propose the still-unanswered tool_use of the latest assistant message, or
suggest finishing. It owns no execution/permission/persistence (05 §0). P1 uses a
single hard-coded strategy; registry / hot-swap / AB are P9 (only ``id``/
``fingerprint`` reserved here, ADR-0009)."""

from __future__ import annotations

from questor.contracts.common import JsonObject
from questor.contracts.policy import PolicyIntent, PolicyPort, PolicyView, ProposeToolCall, SuggestFinish
from questor.contracts.state_schema import OPEN_TOOL_CALL_STATUSES, Role


class ReActPolicy(PolicyPort):
    id = "react"
    fingerprint = "react:1"

    def propose_action(self, view: PolicyView) -> PolicyIntent:
        answered = {c.tool_call_id for c in view.tool_results if c.status not in OPEN_TOOL_CALL_STATUSES}
        last_assistant = next((m for m in reversed(view.context) if m.role is Role.ASSISTANT), None)
        if last_assistant is None:
            return SuggestFinish(final_text=None)

        for block in last_assistant.content:
            if block.type == "tool_use" and block.tool_use_id and block.tool_use_id not in answered:
                args: JsonObject = dict(block.input or {})
                return ProposeToolCall(name=block.name or "", args=args, tool_call_id=block.tool_use_id)

        text = "".join(b.text or "" for b in last_assistant.content if b.type == "text")
        return SuggestFinish(final_text=text or None)


__all__ = ["ReActPolicy"]
