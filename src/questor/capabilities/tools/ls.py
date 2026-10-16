"""内置只读工具：``ls``（design/03 §6）。列目录，跳过噪音目录，条数上限，符号链接越界不展示。"""

from __future__ import annotations

from questor.capabilities.tools._output import preview_bytes
from questor.capabilities.tools._paths import is_skipped_dir, resolve_in_workspace
from questor.contracts.common import JsonObject
from questor.contracts.tool import Capability, Risk, Tool, ToolContext, ToolResult, ToolSpec

_LS_SPEC = ToolSpec(
    name="ls",
    description="List a workspace directory, skipping noise dirs, with an entry cap.",
    params={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "dir under workspace, default '.'"},
            "limit": {"type": "integer", "minimum": 1, "description": "max entries"},
        },
        "additionalProperties": False,
    },
    capability=Capability.READONLY,
    risk=Risk.LOW,
    read_only=True,
    timeout_s=20,
)

_DEFAULT_LIMIT = 500


class LsTool(Tool):
    spec = _LS_SPEC

    def available(self) -> bool:
        return True

    async def execute(self, args: JsonObject, ctx: ToolContext) -> ToolResult:
        res = resolve_in_workspace(str(args.get("path", ".")), root=ctx.workspace_root, cwd=ctx.cwd, must_exist=True)
        if not res.ok or res.path is None:
            return ToolResult(status="error", result=res.error or "invalid path")
        target = res.path
        if ctx.is_cancelled():
            return ToolResult(status="error", result="cancelled")
        if not target.is_dir():
            return ToolResult(status="error", result=f"path is not a directory: {target.name}")
        limit = _as_int(args.get("limit"), _DEFAULT_LIMIT)
        entries: list[str] = []
        truncated = False
        for entry in sorted(target.iterdir(), key=lambda p: p.name):
            if is_skipped_dir(entry.name):
                continue
            entries.append(f"{entry.name}/" if entry.is_dir() else entry.name)
            if len(entries) >= limit:
                truncated = True
                break
        body = preview_bytes("\n".join(entries), 64 * 1024)
        if truncated:
            body += f"\n… [truncated: showing first {limit} entries]"
        return ToolResult(status="success", result=body or "(empty)", display=f"{target}: {len(entries)} entr{'y' if len(entries) == 1 else 'ies'}")


def _as_int(value: object, default: int) -> int:
    try:
        return max(1, int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


__all__ = ["LsTool"]
