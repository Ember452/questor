"""内置编辑工具：``edit``（design/03 §6）。用唯一锚点做字符串替换。

- ``old_string`` 必须命中；命中多处且 ``replace_all`` 为假 → 报错（避免误改）。
- ``replace_all`` 为真 → 全替换并在 display 回报替换次数。
containment 复用 :mod:`_paths`；写权限/敏感路径由上游权限门负责。
"""

from __future__ import annotations

from questor.capabilities.tools._paths import resolve_in_workspace
from questor.contracts.common import JsonObject
from questor.contracts.tool import Capability, Risk, Tool, ToolContext, ToolResult, ToolSpec

_EDIT_SPEC = ToolSpec(
    name="edit",
    description="Replace a unique anchor (or all anchors) in a workspace text file.",
    params={
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "old_string": {"type": "string"},
            "new_string": {"type": "string"},
            "replace_all": {"type": "boolean"},
        },
        "required": ["file_path", "old_string", "new_string"],
        "additionalProperties": False,
    },
    capability=Capability.WRITE,
    risk=Risk.HIGH,
    read_only=False,
    timeout_s=30,
)


class EditTool(Tool):
    """对 workspace 内文本文件做锚点替换。"""

    spec = _EDIT_SPEC

    def available(self) -> bool:
        return True

    async def execute(self, args: JsonObject, ctx: ToolContext) -> ToolResult:
        old = args.get("old_string")
        new = args.get("new_string")
        if not isinstance(old, str) or not old:
            return ToolResult(status="error", result="'old_string' must be a non-empty string")
        if not isinstance(new, str):
            return ToolResult(status="error", result="'new_string' must be a string")
        replace_all = bool(args.get("replace_all", False))
        res = resolve_in_workspace(str(args.get("file_path") or ""), root=ctx.workspace_root, cwd=ctx.cwd, must_exist=True)
        if not res.ok or res.path is None:
            return ToolResult(status="error", result=res.error or "invalid path")
        target = res.path
        if ctx.is_cancelled():
            return ToolResult(status="error", result="cancelled")
        try:
            text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return ToolResult(status="error", result=f"read failed: {exc}")
        count = text.count(old)
        if count == 0:
            return ToolResult(status="error", result=f"anchor not found in {target.name}")
        if count > 1 and not replace_all:
            return ToolResult(status="error", result=f"anchor matches multiple times ({count}) in {target.name}; set replace_all or use a longer anchor")
        updated = text.replace(old, new)
        try:
            target.write_text(updated, encoding="utf-8")
        except OSError as exc:
            return ToolResult(status="error", result=f"write failed: {exc}")
        return ToolResult(status="success", result=f"edited {target.name}", display=f"edited {target} ({count} replacement(s))", files=(str(target),))


__all__ = ["EditTool"]
