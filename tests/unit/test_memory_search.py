"""混合检索纯函数测（design/06 §2；ADR-0026；T10）。钉死：非 RRF、按命中通道加权、core 常绿/daily 半衰。"""

from __future__ import annotations

from datetime import UTC, datetime

from questor.contracts.memory import MemoryStrategyConfig
from questor.memory.search import decay_factor, fuse, rank_scores


def test_rank_scores_linear_normalized_not_rrf() -> None:
    assert rank_scores(0) == []
    # (0,1] 线性归一：第 1 名 1.0，末名 1/n —— 非 RRF 的 1/(k+rank) 调和式。
    assert rank_scores(4) == [1.0, 0.75, 0.5, 0.25]


def test_fuse_both_channel_hit_outranks_single_channel() -> None:
    cfg = MemoryStrategyConfig(vector_weight=0.5, keyword_weight=0.5)
    fused = fuse(keyword_order=["both", "kw_only"], vector_order=["both", "vec_only"], config=cfg)
    assert fused["both"] == 1.0  # 两通道 rank0 → (0.5*1 + 0.5*1)/1.0
    assert fused["both"] > fused["kw_only"]
    assert fused["both"] > fused["vec_only"]


def test_decay_core_evergreen_and_daily_halflife() -> None:
    cfg = MemoryStrategyConfig(half_life_days=30.0)
    now = datetime(2026, 1, 31, tzinfo=UTC)
    assert decay_factor("MEMORY.md", cfg, now) == 1.0  # core 常绿不衰减
    assert abs(decay_factor("memory/2026-01-01.md", cfg, now) - 0.5) < 1e-9  # 恰一个半衰期 → 0.5
    assert decay_factor("memory/2026-01-30.md", cfg, now) > 0.9  # 新条目 ≈1
