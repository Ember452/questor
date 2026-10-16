"""内置 exec 工具：``powershell``（design/03 §6/§7；ADR-0018）。Windows 真机主验收工具。

与 bash 对称：只解析 args → 绝对 argv 的 ``ProcessRequest`` → ``ctx.run_process``；spawn/wrap/
env/超时/进程树清理都在 L5 ProcessRunner。优先 ``pwsh``，回退 ``powershell``；都缺时
``available()`` 为假（POSIX CI 不谎报）。
"""

from __future__ import annotations

import shutil

from questor.capabilities.tools._process import process_to_tool_result
from questor.contracts.common import JsonObject
from questor.contracts.process import ProcessRequest
from questor.contracts.tool import Capability, Risk, Tool, ToolContext, ToolResult, ToolSpec

_POWERSHELL_SPEC = ToolSpec(
    name="powershell",
    description="Run a PowerShell command through the sandboxed process runner (Windows primary).",
    params={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "PowerShell script/command"},
            "timeout": {"type": "number", "exclusiveMinimum": 0},
        },
        "required": ["command"],
        "additionalProperties": False,
    },
    capability=Capability.EXEC,
    risk=Risk.HIGH,
    read_only=False,
    timeout_s=120,
)


def _resolve_program() -> str | None:
    return shutil.which("pwsh") or shutil.which("powershell") or shutil.which("powershell.exe")


class PowerShellTool(Tool):
    spec = _POWERSHELL_SPEC

    def available(self) -> bool:
        return _resolve_program() is not None

    async def execute(self, args: JsonObject, ctx: ToolContext) -> ToolResult:
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            return ToolResult(status="error", result="'command' must be a non-empty string")
        program = _resolve_program()
        if program is None:
            return ToolResult(status="error", result="powershell is not available on this platform")
        if ctx.is_cancelled():
            return ToolResult(status="error", result="cancelled")
        timeout = args.get("timeout")
        request = ProcessRequest(
            capability=Capability.EXEC,
            argv=(program, "-NoProfile", "-Command", command),
            cwd=ctx.cwd,
            timeout_s=float(timeout) if isinstance(timeout, (int, float)) and timeout > 0 else (_POWERSHELL_SPEC.timeout_s or 120),
        )
        result = await ctx.run_process(request)
        return process_to_tool_result(result, name="powershell")


__all__ = ["PowerShellTool"]
