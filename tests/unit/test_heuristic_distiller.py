"""`--dream` 出厂 heuristic 蒸馏器测（链走发现：旧实现只喂 dailies 会越刷越丢 core）。

断言单调性：合并现有 core + 近期 daily，新原料为空也不丢既有精华；无内容返回 None（空哨兵）。"""

from __future__ import annotations

from questor.__main__ import _HeuristicDistiller


async def test_heuristic_distiller_merges_and_keeps_existing_core() -> None:
    out = await _HeuristicDistiller().distill(core="# MEMORY\n- old evergreen fact\n", dailies=["\n## [daily] t\n\nnew fact\n"])
    assert out is not None
    assert "old evergreen fact" in out.new_core  # 不因本次只看 daily 而丢掉既有 core
    assert "new fact" in out.new_core


async def test_heuristic_distiller_returns_none_when_nothing_to_solidify() -> None:
    assert await _HeuristicDistiller().distill(core="", dailies=[]) is None
