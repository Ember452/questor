"""P1's single built-in tool: ``read`` (design/03 §6). P0 = declared shape only.

Real behavior (read a file inside the workspace root, respect the denylist, poll
``is_cancelled``) lands in P1 T5. Business validation lives here (a pure fn),
never in the sandbox (C8)."""

from __future__ import annotations

from questor.contracts.common import JsonObject
from questor.contracts.tool import Capability, Risk, Tool, ToolContext, ToolResult, ToolSpec

_READ_SPEC = ToolSpec(
    name="read",
    description="Read a UTF-8 text file rooted at the workspace.",
    params={
        "type": "object",
        "properties": {"file_path": {"type": "string"}},
        "required": ["file_path"],
        "additionalProperties": False,
    },
    capability=Capability.READONLY,
    risk=Risk.LOW,
    read_only=True,
)


class ReadTool(Tool):
    spec = _READ_SPEC

    def available(self) -> bool:
        return True

    async def execute(self, args: JsonObject, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError("read tool behavior lands in P1 (T5)")
