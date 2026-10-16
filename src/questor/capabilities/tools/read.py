"""内置只读工具：``read``（design/03 §6）。P2 补 offset/limit + 行/字节双上限 + 目录/二进制拒绝。

真正行为（workspace 根内读文件、轮询 ``is_cancelled`` 早退）在 P1 落地；本模块只加参数
边界与输出预算，业务校验留在这里（纯函数），绝不下沉到沙箱（C8）。敏感路径拦截由上游权限门负责。
"""

from __future__ import annotations

from questor.capabilities.tools._output import preview_bytes
from questor.capabilities.tools._paths import resolve_in_workspace
from questor.contracts.common import JsonObject
from questor.contracts.tool import Capability, Risk, Tool, ToolContext, ToolResult, ToolSpec

_READ_SPEC = ToolSpec(
    name="read",
    description="Read a UTF-8 text file (or a line window of it) rooted at the workspace.",
    params={
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "offset": {"type": "integer", "minimum": 0, "description": "0-based line offset"},
            "limit": {"type": "integer", "minimum": 1, "description": "max lines to return"},
        },
        "required": ["file_path"],
        "additionalProperties": False,
    },
    capability=Capability.READONLY,
    risk=Risk.LOW,
    read_only=True,
    timeout_s=30,
)

_MAX_LINES = 2000  # 默认行上限
_MAX_BYTES = 128 * 1024  # 单次返回字节硬上限（行上限之外的第二道闸）


class ReadTool(Tool):
    """读取 workspace 根内的一个 UTF-8 文本文件（可取行窗口）。"""

    spec = _READ_SPEC

    def available(self) -> bool:
        return True

    async def execute(self, args: JsonObject, ctx: ToolContext) -> ToolResult:
        """读 file_path；越界/缺失/目录/二进制/取消/IO 错误都回 error（不抛），维持配对。"""
        raw = args.get("file_path")
        res = resolve_in_workspace(str(raw) if raw is not None else "", root=ctx.workspace_root, cwd=ctx.cwd, must_exist=True)
        if not res.ok or res.path is None:
            return ToolResult(status="error", result=res.error or "invalid path")
        target = res.path
        if ctx.is_cancelled():
            return ToolResult(status="error", result="cancelled")
        if target.is_dir():
            return ToolResult(status="error", result=f"path is a directory: {target.name}")
        try:
            data = target.read_bytes()
        except OSError as exc:
            return ToolResult(status="error", result=f"read failed: {exc}")
        if b"\x00" in data[:8192]:  # 前若干字节含 NUL 视为二进制
            return ToolResult(status="error", result=f"binary file, not text: {target.name}")
        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()
        total_lines = len(lines)
        offset = _as_int(args.get("offset"), 0)
        limit = _as_int(args.get("limit"), _MAX_LINES)
        window = lines[offset : offset + limit]
        body = "\n".join(window)
        truncated_lines = offset + len(window) < total_lines
        bounded = preview_bytes(body, _MAX_BYTES)
        truncated_bytes = len(bounded) < len(body.encode("utf-8"))
        result = bounded
        if truncated_lines or truncated_bytes:
            result = bounded + f"\n… [truncated: showing lines {offset + 1}-{offset + len(window)} of {total_lines}]"
        display = f"read {target.name}: lines {offset + 1}-{offset + len(window)} of {total_lines}"
        return ToolResult(status="success", result=result, display=display)


def _as_int(value: object, default: int) -> int:
    try:
        return max(0, int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


__all__ = ["ReadTool"]
