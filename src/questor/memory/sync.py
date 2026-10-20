"""记忆索引重建的纯映射（design/06 §0：文件真源、索引派生投影）。

把"已读到的 md 文件内容"映射为待索引的 chunk 集合——**无 IO、无 store 依赖、可单测**。调用方
（``providers.store_memory_sqlite.SQLiteMemoryStore.sync``）负责扫盘读文件、清索引、逐块 reindex。

文件 → source 映射：``MEMORY.md``→core、
``knowledge/**``→knowledge、``memory/<date>.md``→daily；**``memory/dreams/**`` 不进索引**
（design/06 §1：蒸馏日记作常绿精华来源，但排除出检索层，防近重复噪声）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from questor.contracts.memory import MemoryChunk, MemoryScope, MemorySource
from questor.memory.chunker import chunk_document


@dataclass(frozen=True, slots=True)
class LayoutRule:
    """一条布局规则：路径前缀 → 记忆层，**顺序就是优先级**（B9 / OPT-9）。

    `dreams/` 必须排在 `memory/` 前面：两者都是 `memory/` 下的子目录，顺序反了
    蒸馏日记会被当 daily 索引进检索层（design/06 §1 禁止的近重复噪声就回来了）。
    """

    prefix: str
    source: MemorySource | None


#: 有序布局表（取代旧 if 链；新增布局只加一行，不改判定顺序的人不用重读函数体）。
LAYOUT_RULES: tuple[LayoutRule, ...] = (
    LayoutRule(prefix="memory/dreams/", source=None),  # 不索引（蒸馏日记）
    LayoutRule(prefix="dreams/", source=None),
    LayoutRule(prefix="knowledge/", source=MemorySource.KNOWLEDGE),
    LayoutRule(prefix="memory/", source=MemorySource.DAILY),
    LayoutRule(prefix="memory.md", source=MemorySource.CORE),
)


def source_for_path(rel_path: str) -> MemorySource | None:
    """按相对路径判定记忆层；返回 ``None`` 表示该文件不进检索索引（如 dreams）。

    规则按 :data:`LAYOUT_RULES` 顺序取**首个前缀命中**，所以 dreams 先于 memory/；
    `MEMORY.md` 是整名而非目录，单独判。行为与旧的 if 链逐字等价。
    """
    p = rel_path.replace("\\", "/").lower()
    if p == "memory.md":
        return MemorySource.CORE
    for rule in LAYOUT_RULES:
        if p.startswith(rule.prefix):
            return rule.source
    return None


def build_chunks(files: Mapping[str, str], *, scope: MemoryScope = MemoryScope.USER) -> tuple[MemoryChunk, ...]:
    """把 ``{相对路径: 文本}`` 全量切成待索引 chunk；跳过非记忆层与 dreams。"""
    chunks: list[MemoryChunk] = []
    for rel, text in files.items():
        source = source_for_path(rel)
        if source is None:
            continue
        chunks.extend(chunk_document(rel.replace("\\", "/"), text, source=source, scope=scope))
    return tuple(chunks)
