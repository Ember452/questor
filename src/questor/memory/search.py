"""记忆混合检索（design/06 §2；ADR-0026；承 CowAgent ``manager.py:722-742,657-697`` 自写）。

**纯函数、无 IO**：把关键词通道与向量通道的候选按名次融合，再施时间衰减。可插拔性（DoD④）
落在 ``MemoryStrategyConfig``——换权重/半衰期即换检索行为，不动 kernel。融合口径严格按
design/06 §2：**rank-normalize 到 (0,1] 加权、非 RRF**；**只在命中的通道上做加权平均**并归一
（防 NaN/负）；core/knowledge 常绿、daily 指数半衰。

向量降级由调用方（store）负责：无 embedding/向量后端不可用时只传 keyword 候选，本模块自然
退化成关键词单通道。"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime

from questor.contracts.memory import MemoryStrategyConfig

#: daily 文件名里的日期（memory/YYYY-MM-DD.md）；core/knowledge/dreams 不匹配 → 常绿。
_DAILY_DATE = re.compile(r"memory/(\d{4}-\d{2}-\d{2})\.md")


def rank_scores(n: int) -> list[float]:
    """按名次线性归一到 (0,1]：第 1 名 = 1.0，末名 = 1/n。**非 RRF**（design/06 §2）。"""
    if n <= 0:
        return []
    return [(n - i) / n for i in range(n)]


def fuse(
    keyword_order: Sequence[str],
    vector_order: Sequence[str],
    config: MemoryStrategyConfig,
) -> dict[str, float]:
    """融合两通道候选为 ``{chunk_id: score}``：仅对命中的通道加权、按命中权重之和归一。

    ``keyword_order``/``vector_order`` 是各通道按相关性降序的 chunk id 列表（越靠前越相关）。"""
    kw = dict(zip(keyword_order, rank_scores(len(keyword_order)), strict=True))
    vec = dict(zip(vector_order, rank_scores(len(vector_order)), strict=True))
    fused: dict[str, float] = {}
    for cid in set(kw) | set(vec):
        acc = 0.0
        wsum = 0.0
        if cid in vec:
            acc += config.vector_weight * vec[cid]
            wsum += config.vector_weight
        if cid in kw:
            acc += config.keyword_weight * kw[cid]
            wsum += config.keyword_weight
        fused[cid] = acc / wsum if wsum > 0 else 0.0
    return fused


def decay_factor(path: str, config: MemoryStrategyConfig, now: datetime) -> float:
    """时间衰减：带日期 daily 指数半衰（``0.5 ** (age/half_life)``）；core/knowledge/dreams 恒 1.0。"""
    match = _DAILY_DATE.search(path.replace("\\", "/"))
    if match is None:
        return 1.0
    try:
        day = datetime.strptime(match.group(1), "%Y-%m-%d").replace(tzinfo=now.tzinfo)
    except ValueError:
        return 1.0
    age_days = max(0.0, (now - day).total_seconds() / 86400.0)
    return 0.5 ** (age_days / config.half_life_days)
