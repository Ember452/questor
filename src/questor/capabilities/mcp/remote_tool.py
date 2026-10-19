"""L3 远程 MCP 工具 → ToolSpec 映射与执行（C19/C22；`docs/plan/05` T3/T11）。

一个远程工具映射成 `ToolSpec` + `Tool` 实现，经同一注册表/权限/沙箱/账本路径（`README.md` 约定）：
- 命名 `mcp_<server>_<tool>`（C20）；描述过共享 `bound_description` 有界净化（C19/C18）；
  inputSchema 过 `normalize_mcp_schema` 归一（C18）。
- **C22 非放宽**：capability=NETWORK、risk=MEDIUM、read_only 默认 False（远程 annotations 是 hint
  非 grant）、approval_mode 不设 → 由权限层走 unknown→deny。
- **C19 闭合**：远程返回 `isError` → `ToolResult(status="error")`（真实记录，非合成）；transport/连接
  异常**向上抛**，由 Harness `_execute_tool` 归一成 error/timed_out 的 `tool_result` 闭合配对，绝不吞成成功。
分层：本模块在 L3，经注入的 connection 调远程，不 import store/surfaces（HARD C1/C14）。
"""

from __future__ import annotations

import json
from typing import Any

from questor.capabilities.mcp.naming import remote_tool_name
from questor.capabilities.mcp.schema import normalize_mcp_schema
from questor.capabilities.tools.registry import bound_description
from questor.contracts.common import JsonObject
from questor.contracts.tool import Capability, Risk, Tool, ToolContext, ToolResult, ToolSpec

_DESCRIPTION_MAX = 2000


def _extract_text(result: Any) -> str:
    """把 SDK CallToolResult 的文本块拼成给模型的字符串；无文本块时回落 structuredContent。"""
    parts = [block.text for block in (getattr(result, "content", None) or ()) if isinstance(getattr(block, "text", None), str)]
    if not parts:
        structured = getattr(result, "structuredContent", None)
        if structured is not None:
            parts.append(json.dumps(structured, ensure_ascii=False, sort_keys=True, default=str))
    return "\n".join(parts) or "(no output)"


class McpRemoteTool(Tool):
    """把一个远程 MCP 工具适配成本地 `Tool`；调用经注入的 connection，不持裸 SDK 句柄于 kernel。"""

    def __init__(
        self,
        *,
        connection: Any,
        server_name: str,
        raw_name: str,
        description: str,
        input_schema: Any,
    ) -> None:
        self._connection = connection
        self._raw_name = raw_name
        self.spec = ToolSpec(
            name=remote_tool_name(server_name, raw_name),
            description=bound_description(str(description or ""), name=raw_name, max_chars=_DESCRIPTION_MAX),
            params=normalize_mcp_schema(input_schema),
            capability=Capability.NETWORK,
            risk=Risk.MEDIUM,
            read_only=False,  # C22：远程 read-only 注解只是 hint，默认按非只读 fail-closed
        )

    def available(self) -> bool:
        # 连接断开时隐藏该工具面（但已发出的在途调用由 C19 组测试证明会闭合，不靠此项兜）。
        return bool(self._connection.connected)

    async def execute(self, args: JsonObject, ctx: ToolContext) -> ToolResult:
        """调用远程工具。isError→error 结果；transport 异常上抛交 Harness 闭合配对（C19）。"""
        result = await self._connection.call_tool(self._raw_name, dict(args))
        text = _extract_text(result)
        if getattr(result, "isError", False):
            return ToolResult(status="error", result=text, display=f"{self.spec.name} returned an error")
        return ToolResult(status="success", result=text)
