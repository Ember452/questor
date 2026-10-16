"""内置只读工具：``glob``（design/03 §6）。按模式匹配 workspace 内文件，跳过噪音目录与越界符号链接。"""

from __future__ import annotations

from pathlib import Path

from questor.capabilities.tools._output import preview_bytes
from questor.capabilities.tools._paths import SKIP_DIR_NAMES, resolve_in_workspace
from questor.contracts.common import JsonObject
from questor.contracts.tool import Capability, Risk, Tool, ToolContext, ToolResult, ToolSpec

_GLOB_SPEC = ToolSpec(
    name="glob",
    description="Find workspace files by glob pattern, skipping noise dirs and escaped links.",
    params={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "glob like '**/*.py'"},
            "path": {"type": "string", "description": "search root under workspace, default '.'"},
            "limit": {"type": "integer", "minimum": 1},
        },
        "required": ["pattern"],
        "additionalProperties": False,
    },
    capability=Capability.READONLY,
    risk=Risk.LOW,
    read_only=True,
    timeout_s=20,
)

_DEFAULT_LIMIT = 1000


def _has_skipped_component(rel_parts: tuple[str, ...]) -> bool:
    return any(part in SKIP_DIR_NAMES for part in rel_parts)


class GlobTool(Tool):
    spec = _GLOB_SPEC

    def available(self) -> bool:
        return True

    async def execute(self, args: JsonObject, ctx: ToolContext) -> ToolResult:
        pattern = args.get("pattern")
        if not isinstance(pattern, str) or not pattern.strip():
            return ToolResult(status="error", result="'pattern' must be a non-empty glob")
        base = resolve_in_workspace(str(args.get("path", ".")), root=ctx.workspace_root, cwd=ctx.cwd, must_exist=True)
        if not base.ok or base.path is None:
            return ToolResult(status="error", result=base.error or "invalid path")
        if ctx.is_cancelled():
            return ToolResult(status="error", result="cancelled")
        root = ctx.workspace_root.resolve()
        limit = _as_int(args.get("limit"), _DEFAULT_LIMIT)
        results: list[str] = []
        truncated = False
        try:
            for match in sorted(base.path.glob(pattern)):
                if ctx.is_cancelled():
                    return ToolResult(status="error", result="cancelled")
                if not match.is_file():
                    continue
                try:
                    rel = match.relative_to(root)
                except ValueError:
                    continue
                if _has_skipped_component(rel.parts):
                    continue
                # 符号链接越界：realpath 落在 root 之外则跳过。
                try:
                    resolved = match.resolve()
                    Path(str(resolved)).relative_to(root)
                except (OSError, ValueError):
                    continue
                results.append(rel.as_posix())
                if len(results) >= limit:
                    truncated = True
                    break
        except (OSError, ValueError) as exc:
            return ToolResult(status="error", result=f"glob failed: {exc}")
        body = preview_bytes("\n".join(results), 64 * 1024)
        if truncated:
            body += f"\n… [truncated: showing first {limit} matches]"
        return ToolResult(status="success", result=body or "(no matches)", display=f"glob {pattern}: {len(results)} match(es)")


def _as_int(value: object, default: int) -> int:
    try:
        return max(1, int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


__all__ = ["GlobTool"]
