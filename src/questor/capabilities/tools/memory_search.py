"""内置只读记忆检索工具：``memory_search``（design/06 §0/§2；ADR-0026；T12）。

策略只能"提议调用 memory_search + 参数"；检索经 Harness 持有的 ``MemoryStorePort``（由
``ctx.memory_search`` 暴露）返回**有界**片段 ``(path, start_line, end_line, snippet)``——工具
拿不到向量库/SQLite 裸句柄（HARD C4，Cow 实证）。业务侧无 IO（IO 在 provider/子系统），
本工具只做参数校验 + 有界投影（HARD C8/C18）。
"""

from __future__ import annotations

from questor.contracts.common import JsonObject
from questor.contracts.tool import Capability, Risk, Tool, ToolContext, ToolResult, ToolSpec

_SPEC = ToolSpec(
    name="memory_search",
    description="Search long-term memory (hybrid vector + keyword) for bounded snippets; read-only; no raw store handle.",
    params={
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1, "maxLength": 512},
            "k": {"type": "integer", "minimum": 1, "maximum": 32, "description": "max hits to return"},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    capability=Capability.MEMORY,
    risk=Risk.LOW,
    read_only=True,
    timeout_s=30,
)


class MemorySearchTool(Tool):
    """经 ``ctx.memory_search`` 取有界记忆命中；不 import provider/store（C1/C4）。"""

    spec = _SPEC

    def available(self) -> bool:
        return True

    async def execute(self, args: JsonObject, ctx: ToolContext) -> ToolResult:
        """检索记忆；无命中/无后端回**有界空态**（不抛），非法 query 回 error（维持配对）。"""
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            return ToolResult(status="error", result="memory_search requires a non-empty query")
        if ctx.is_cancelled():
            return ToolResult(status="error", result="cancelled")
        k_raw = args.get("k", 8)
        try:
            k = int(k_raw) if k_raw is not None else 8
        except (TypeError, ValueError):
            k = 8
        k = max(1, min(k, 32))  # 上限双保险：防一次拉爆 prompt（HARD C18）
        hits = await ctx.memory_search(query, k=k)
        payload = [
            {
                "path": h.path,
                "start_line": h.start_line,
                "end_line": h.end_line,
                "score": round(h.score, 4),
                "snippet": h.snippet,
            }
            for h in hits
        ]
        if not payload:
            return ToolResult(status="success", result="no memory matches", display={"hits": []})
        return ToolResult(status="success", result=payload, display={"hits": payload})
