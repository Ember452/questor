"""P1 的唯一内置工具：``read``（design/03 §6）。P0 只声明形状。

真正行为（在 workspace 根内读文件、轮询 ``is_cancelled`` 早退）在 P1 T5 落地。业务
校验留在这里（纯函数），绝不下沉到沙箱（C8）。敏感路径的拦截由上游权限门负责。"""

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
    """读取 workspace 根内的一个 UTF-8 文本文件。"""

    spec = _READ_SPEC

    def available(self) -> bool:
        return True

    async def execute(self, args: JsonObject, ctx: ToolContext) -> ToolResult:
        """读取 file_path；越界/缺失/取消/IO 错误都回 error（不抛），维持配对。"""
        raw = args.get("file_path")
        if not isinstance(raw, str) or not raw.strip():
            return ToolResult(status="error", result="missing or empty 'file_path'")
        root = Path(ctx.workspace_root).resolve()
        candidate = Path(raw)
        target = (candidate if candidate.is_absolute() else root / candidate).resolve()
        # 边界检查：拒读 workspace 根之外（纵深防御；敏感路径 denylist 已由权限门更早拦截）。
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
