"""记忆切块（design/06 §5 取料 #4；承 CowAgent ``chunker.py`` 思路自写，非逐行移植）。

纯函数、无 IO、只依赖 contracts：把一篇 markdown 文档切成带**行区间**的 :class:`MemoryChunk`。
markdown 结构感知（按标题切段）+ 超长滑窗（overlap 防切断语义）。``CHUNKER_VERSION`` 变更触发
``sync`` 全量重建（切块策略与历史索引不兼容时宁可重建，别静默半旧）。``scope``/``source`` 由
调用方（``sync``）按文件布局给定，本模块不关心文件路径语义。
"""

from __future__ import annotations

import hashlib

from questor.contracts.memory import MemoryChunk, MemoryScope, MemorySource

#: 切块策略版本；改动切块逻辑即 bump，sync 见版本不符则全量重建。
CHUNKER_VERSION = 1
#: 单块最大行数；超出滑窗切分。经验值，够容纳一个完整小节。
_MAX_LINES = 40
#: 滑窗相邻块重叠行数，保语义连续、防边界丢信息。
_OVERLAP = 4


def _make_chunk(rel_path: str, source: MemorySource, scope: MemoryScope, start: int, end: int, lines: list[str]) -> MemoryChunk:
    """据行区间构造一个 chunk：id=md5(path:start:end)，hash=sha256(text)。"""
    text = "\n".join(lines).strip()
    cid = hashlib.md5(f"{rel_path}:{start}:{end}".encode()).hexdigest()
    return MemoryChunk(
        id=cid,
        scope=scope,
        source=source,
        path=rel_path,
        start_line=start,
        end_line=end,
        text=text,
        hash=hashlib.sha256(text.encode()).hexdigest(),
    )


def chunk_document(
    rel_path: str, content: str, *, source: MemorySource, scope: MemoryScope
) -> tuple[MemoryChunk, ...]:
    """把一篇文档切成 chunk 序列（行区间 1-based、含端点）。空文/空块跳过。"""
    lines = content.splitlines()
    if not lines:
        return ()
    # 1) 按 markdown 标题（# 开头）切段，无标题则整篇一段。
    blocks: list[tuple[int, list[str]]] = []  # (起始行号, 行)
    cur_start = 1
    cur: list[str] = []
    for i, ln in enumerate(lines, start=1):
        if ln.startswith("#") and cur:
            blocks.append((cur_start, cur))
            cur_start, cur = i, [ln]
        else:
            cur.append(ln)
    if cur:
        blocks.append((cur_start, cur))
    # 2) 每段：<=_MAX_LINES 整段一 chunk；否则滑窗切、相邻块 overlap。
    chunks: list[MemoryChunk] = []
    for start_line, blines in blocks:
        if len(blines) <= _MAX_LINES:
            end_line = start_line + len(blines) - 1
            if "\n".join(blines).strip():
                chunks.append(_make_chunk(rel_path, source, scope, start_line, end_line, blines))
            continue
        step = _MAX_LINES - _OVERLAP
        offset = 0
        while offset < len(blines):
            window = blines[offset : offset + _MAX_LINES]
            start = start_line + offset
            end = min(start_line + offset + len(window) - 1, start_line + len(blines) - 1)
            if "\n".join(window).strip():
                chunks.append(_make_chunk(rel_path, source, scope, start, end, window))
            if offset + _MAX_LINES >= len(blines):
                break
            offset += step
    return tuple(chunks)
