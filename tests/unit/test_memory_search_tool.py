"""memory_search 工具单测（T12）。用桩 ``ToolContext`` 证明：工具只经 ctx.memory_search 取有界
投影、不碰裸句柄；非法/空/取消回 error；无命中回有界空态（不抛）；k 被夹到 [1,32]。"""

from __future__ import annotations

from pathlib import Path

from questor.capabilities.tools.memory_search import MemorySearchTool
from questor.contracts.memory import MemorySearchResult, MemorySource


class _Ctx:
    """实现 ToolContext Protocol 所需最小面（memory_search + is_cancelled）的桩。"""

    def __init__(self, hits, *, cancelled: bool = False, recorded_k=None) -> None:
        self._hits = hits
        self._cancelled = cancelled
        self.recorded_k = recorded_k
        self.workspace_root = Path(".")
        self.cwd = Path(".")

    def is_cancelled(self) -> bool:
        return self._cancelled

    async def memory_search(self, query, *, k: int = 8, scope=None):
        self.recorded_k = k
        return tuple(self._hits)


def _hit(marker: str = "MARINA77") -> MemorySearchResult:
    return MemorySearchResult(
        path="memory/2026-10-16.md",
        start_line=3,
        end_line=5,
        score=0.9,
        snippet=f"favorite id is {marker}",
        source=MemorySource.DAILY,
    )


async def test_returns_bounded_projection() -> None:
    tool = MemorySearchTool()
    result = await tool.execute({"query": "MARINA77"}, _Ctx([_hit()]))
    assert result.status == "success"
    assert result.result[0]["snippet"] == "favorite id is MARINA77"
    assert result.result[0]["path"] == "memory/2026-10-16.md"


async def test_empty_query_errors() -> None:
    result = await MemorySearchTool().execute({"query": "   "}, _Ctx([]))
    assert result.status == "error"


async def test_cancelled_errors() -> None:
    result = await MemorySearchTool().execute({"query": "x"}, _Ctx([_hit()], cancelled=True))
    assert result.status == "error"


async def test_no_store_returns_empty_state_not_raise() -> None:
    result = await MemorySearchTool().execute({"query": "anything"}, _Ctx([]))
    assert result.status == "success"
    assert result.result == "no memory matches"


async def test_k_clamped_to_range() -> None:
    ctx = _Ctx([_hit()])
    await MemorySearchTool().execute({"query": "MARINA77", "k": 1000}, ctx)
    assert ctx.recorded_k == 32  # 上限夹到 32（HARD C18 防拉爆）
