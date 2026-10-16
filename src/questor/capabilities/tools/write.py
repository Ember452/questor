"""内置写工具：``write``（design/03 §6/§7）。创建或覆盖 workspace 内的文本文件。

containment 由共享 :mod:`_paths` 保证；protected root / 无沙箱围栏的 ask 由上游权限门更早
拦截，这里只负责"给定路径合法则落盘"的业务动作。绝不 import provider/store/sandbox/UI（C1）。
"""

from __future__ import annotations

from questor.capabilities.tools._paths import resolve_in_workspace
from questor.contracts.common import JsonObject
from questor.contracts.tool import Capability, Risk, Tool, ToolContext, ToolResult, ToolSpec

_WRITE_SPEC = ToolSpec(
    name="write",
    description="Create or overwrite a UTF-8 text file inside the workspace root.",
    params={
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["file_path", "content"],
        "additionalProperties": False,
    },
    capability=Capability.WRITE,
    risk=Risk.HIGH,
    read_only=False,
    timeout_s=30,
)


class WriteTool(Tool):
    """在 workspace 根内写入（覆盖）一个文本文件。"""

    spec = _WRITE_SPEC

    def available(self) -> bool:
        return True

    async def execute(self, args: JsonObject, ctx: ToolContext) -> ToolResult:
        content = args.get("content")
        if not isinstance(content, str):
            return ToolResult(status="error", result="'content' must be a string")
        res = resolve_in_workspace(str(args.get("file_path") or ""), root=ctx.workspace_root, cwd=ctx.cwd)
        if not res.ok or res.path is None:
            return ToolResult(status="error", result=res.error or "invalid path")
        target = res.path
        if ctx.is_cancelled():
            return ToolResult(status="error", result="cancelled")
        if target.is_dir():
            return ToolResult(status="error", result=f"path is a directory: {target.name}")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            return ToolResult(status="error", result=f"write failed: {exc}")
        return ToolResult(status="success", result=f"wrote {len(content)} chars to {target.name}", display=f"wrote {target} ({len(content)} chars)", files=(str(target),))


__all__ = ["WriteTool"]
