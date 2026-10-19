"""记忆索引重建的纯映射（design/06 §0：文件真源、索引派生投影）。

把"已读到的 md 文件内容"映射为待索引的 chunk 集合——**无 IO、无 store 依赖、可单测**。调用方
（``providers.store_memory_sqlite.SQLiteMemoryStore.sync``）负责扫盘读文件、清索引、逐块 reindex。

文件 → source 映射：``MEMORY.md``→core、
``knowledge/**``→knowledge、``memory/<date>.md``→daily；**``memory/dreams/**`` 不进索引**
（design/06 §1：蒸馏日记作常绿精华来源，但排除出检索层，防近重复噪声）。
"""

from __future__ import annotations

from collections.abc import Mapping

from questor.contracts.memory import MemoryChunk, MemoryScope, MemorySource
from questor.memory.chunker import chunk_document


def source_for_path(rel_path: str) -> MemorySource | None:
    """按相对路径判定记忆层；返回 ``None`` 表示该文件不进检索索引（如 dreams）。"""
    p = rel_path.replace("\\", "/").lower()
    if p.startswith("memory/dreams/"):
        return None
    if p == "memory.md":
        return MemorySource.CORE
    if p.startswith("knowledge/"):
        return MemorySource.KNOWLEDGE
    if p.startswith("memory/"):
        return MemorySource.DAILY
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
