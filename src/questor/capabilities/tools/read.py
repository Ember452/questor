"""P1's single built-in tool: ``read`` (design/03 §6). P0 = declared shape only.

Real behavior (read a file inside the workspace root, respect the denylist, poll
``is_cancelled``) lands in P1 T5. Business validation lives here (a pure fn),
never in the sandbox (C8)."""

from __future__ import annotations

import os
from pathlib import Path

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
        raw = args.get("file_path")
        if not isinstance(raw, str) or not raw.strip():
            return ToolResult(status="error", result="missing or empty 'file_path'")
        root = Path(ctx.workspace_root).resolve()
        candidate = Path(raw)
        target = (candidate if candidate.is_absolute() else root / candidate).resolve()
        # Boundary check: refuse to read outside the workspace root (defense-in-
        # depth; the sensitive-path denylist is enforced earlier by the gate).
        try:
            target.relative_to(root)
        except ValueError:
            return ToolResult(status="error", result=f"path escapes workspace root: {raw}")
        if ctx.is_cancelled():
            return ToolResult(status="error", result="cancelled")
        if not target.is_file():
            return ToolResult(status="error", result=f"not a file: {os.path.basename(str(target))}")
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return ToolResult(status="error", result=f"read failed: {exc}")
        return ToolResult(status="success", result=text, display=f"read {target.name} ({len(text)} chars)")
