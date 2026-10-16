"""内置 exec 工具：``bash``（design/03 §6/§7；ADR-0018）。只解析 args → ProcessRequest → ctx.run_process。

本工具绝不 import subprocess/asyncio.create_subprocess/沙箱具体实现——真正的 spawn、wrap、
env scrub、超时、进程树清理都在 Harness-owned ProcessRunner（L5）里完成。缺 bash 的平台
``available()`` 为假（Windows 本机不谎报）。
"""

from __future__ import annotations

import shutil

from questor.capabilities.tools._process import process_to_tool_result
from questor.contracts.common import JsonObject
from questor.contracts.process import ProcessRequest
from questor.contracts.tool import Capability, Risk, Tool, ToolContext, ToolResult, ToolSpec

_BASH_SPEC = ToolSpec(
    name="bash",
    description="Run a POSIX shell command through the sandboxed process runner.",
    params={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "POSIX shell script"},
            "timeout": {"type": "number", "exclusiveMinimum": 0, "description": "override timeout seconds"},
        },
        "required": ["command"],
        "additionalProperties": False,
    },
    capability=Capability.EXEC,
    risk=Risk.HIGH,
    read_only=False,
    timeout_s=120,
)


class BashTool(Tool):
    spec = _BASH_SPEC

    def available(self) -> bool:
        """本机有 bash 才可用（Windows 默认无 → 隐藏，不谎报覆盖）。"""
        return shutil.which("bash") is not None

    async def execute(self, args: JsonObject, ctx: ToolContext) -> ToolResult:
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            return ToolResult(status="error", result="'command' must be a non-empty string")
        program = shutil.which("bash")
        if program is None:
            return ToolResult(status="error", result="bash is not available on this platform")
        if ctx.is_cancelled():
            return ToolResult(status="error", result="cancelled")
        timeout = args.get("timeout")
        request = ProcessRequest(
            capability=Capability.EXEC,
            argv=(program, "-lc", command),
            cwd=ctx.cwd,
            timeout_s=float(timeout) if isinstance(timeout, (int, float)) and timeout > 0 else (_BASH_SPEC.timeout_s or 120),
        )
        result = await ctx.run_process(request)
        return process_to_tool_result(result, name="bash")


__all__ = ["BashTool"]
