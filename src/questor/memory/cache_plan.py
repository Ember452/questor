"""L4 prompt cache 计划（B7；v3 §6.1 cache 三条款）。

**纯函数、无 IO**：把"一次请求的可缓存前缀"算成断点预算 + 三段指纹，供装配方与 kernel 观测。
三条款的落点：

1. **断点预算表**（Anthropic 最多 4 个 ``cache_control`` 断点）：固定四槽
   ``system`` / ``history_start`` / ``tool_face`` / ``reserved``。超预算时 **fail-soft：砍断点不砍内容**
   （被砍的槽位记进 :attr:`CachePlan.dropped`，事件里以 ``reason="budget"`` 出声）。
2. **TTL 门控**：:func:`cache_ttl_for` —— 主对话回合长 TTL；side-query（召回终选器/摘要器）
   **不开 cache**，免得内部调用污染用户的前缀资产。
3. **断裂检测**：三段 hash（system 块 / 工具面 / 历史起点）+ 原因位，发 live-only ``cache_break``；
   hash 不可逆，零明文（C18/C20）。

frozen/fresh 二分的替换选择住在 :func:`replacement_order`：**已展示过的前缀是缓存资产**，
超预算时优先替换 fresh（尾部易变段），frozen 单独超预算则接受超额（交给压缩清），
不去动 frozen —— 动它必然全量断裂，比省下的 token 贵得多。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

#: Anthropic API 的 cache 断点上限（§6.1 条款 1）。
MAX_CACHE_BREAKPOINTS = 4

#: 固定四槽（顺序即预算优先级；名字进事件/dropped 列表，稳定可断言）。
BREAKPOINT_SLOTS: tuple[str, ...] = ("system", "history_start", "tool_face", "reserved")

#: 主对话回合用长 TTL；其余（side-query）不开 cache。
MAIN_SOURCE = "main"
LONG_TTL = "long"


def _hash(label: str, payload: str) -> str:
    """带前缀的 sha256 指纹（不可逆、跨进程稳定；刻意不用 repr）。"""
    return f"sha256:{hashlib.sha256(f'{label}={payload}'.encode()).hexdigest()[:32]}"


@dataclass(frozen=True, slots=True)
class CacheSegments:
    """一次请求里"可缓存的三块前缀"。空块以 ``None`` 表示（不参与断裂判定）。"""

    system: str | None = None
    tools: tuple[str, ...] = ()
    history_start: int | None = None


@dataclass(frozen=True, slots=True)
class CachePlan:
    """断点预算 + 三段指纹的结果（事件载荷由 :meth:`event_data` 出）。"""

    breakpoints: tuple[str, ...]
    dropped: tuple[str, ...]
    system_hash: str | None
    tools_hash: str | None
    history_hash: str | None

    def event_data(self, *, reason: str) -> dict[str, object]:
        """``cache_break`` 的载荷：三段 hash + 原因 + 实得断点数（**无正文**，C18/C20）。"""
        return {
            "system_hash": self.system_hash,
            "tools_hash": self.tools_hash,
            "history_hash": self.history_hash,
            "reason": reason,
            "breakpoints": len(self.breakpoints),
        }


def plan_cache(segments: CacheSegments, *, max_breakpoints: int = MAX_CACHE_BREAKPOINTS) -> CachePlan:
    """按槽位顺序分配断点；超预算即砍**尾部**槽位（fail-soft，不砍内容）。"""
    wanted = [
        ("system", segments.system),
        ("history_start", None if segments.history_start is None else str(segments.history_start)),
        ("tool_face", ",".join(segments.tools) if segments.tools else None),
        ("reserved", None),
    ]
    granted: list[str] = []
    dropped: list[str] = []
    limit = max(0, min(max_breakpoints, MAX_CACHE_BREAKPOINTS))
    for name, payload in wanted:
        if payload is None:
            continue  # 空段不占断点（也不算被砍）
        if len(granted) >= limit:
            dropped.append(name)
        else:
            granted.append(name)
    return CachePlan(
        breakpoints=tuple(granted),
        dropped=tuple(dropped),
        system_hash=_hash("system", segments.system) if segments.system else None,
        tools_hash=_hash("tools", ",".join(segments.tools)) if segments.tools else None,
        history_hash=_hash("history", str(segments.history_start)) if segments.history_start is not None else None,
    )


def cache_ttl_for(query_source: str | None) -> str | None:
    """条款 2：TTL 门控。只有主对话回合拿长 TTL；side-query/未知来源一律 **不开 cache**。"""
    return LONG_TTL if (query_source or "").strip().lower() == MAIN_SOURCE else None


def break_reason(previous: CachePlan | None, current: CachePlan) -> str | None:
    """与上一轮的比对结果：``None`` = 无断裂；否则给出**第一个**变化的维度。

    首轮（``previous is None``）不算断裂，只建基线；断点数变少记 ``budget``（砍断点是设计许可的
    fail-soft，但必须出声，否则"cache 怎么又没命中"无从排查）。
    """
    if previous is None:
        return None
    if previous.system_hash != current.system_hash:
        return "system"
    if previous.tools_hash != current.tools_hash:
        return "tools"
    if previous.history_hash != current.history_hash:
        return "history"
    if len(current.breakpoints) < len(previous.breakpoints):
        return "budget"
    return None


def replacement_order(frozen_bytes: int, fresh_bytes: int, budget: int) -> tuple[str, ...]:
    """frozen/fresh 二分的替换优先级：先 fresh 后 frozen；frozen 单独超预算也**不动它**。"""
    if fresh_bytes >= budget:
        return ("fresh",)
    if frozen_bytes > budget:
        # 已展示过的前缀是缓存资产：宁可暂时超额，等一次真正的压缩，也不撕掉缓存。
        return ("fresh",)
    return ("fresh", "frozen")


__all__ = [
    "BREAKPOINT_SLOTS",
    "LONG_TTL",
    "MAX_CACHE_BREAKPOINTS",
    "CachePlan",
    "CacheSegments",
    "break_reason",
    "cache_ttl_for",
    "plan_cache",
    "replacement_order",
]
