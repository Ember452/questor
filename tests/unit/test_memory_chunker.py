"""记忆切块纯函数测（design/06 §5 #4；T9）。"""

from __future__ import annotations

from questor.contracts.memory import MemoryScope, MemorySource
from questor.memory.chunker import chunk_document


def test_splits_on_markdown_headings() -> None:
    content = "# A\nfact one\n# B\nfact two\n"
    chunks = chunk_document("MEMORY.md", content, source=MemorySource.CORE, scope=MemoryScope.USER)
    assert len(chunks) == 2
    assert "fact one" in chunks[0].text
    assert "fact two" in chunks[1].text
    assert chunks[0].start_line <= chunks[0].end_line
    assert chunks[1].start_line > chunks[0].end_line  # 区间不重叠越界


def test_empty_document_yields_no_chunks() -> None:
    assert chunk_document("x.md", "", source=MemorySource.DAILY, scope=MemoryScope.USER) == ()


def test_long_section_windows_with_overlap() -> None:
    body = "\n".join(f"line {i}" for i in range(100))
    content = f"# Big\n{body}"
    chunks = chunk_document("memory/2026-01-01.md", content, source=MemorySource.DAILY, scope=MemoryScope.USER)
    assert len(chunks) > 1  # 超长段滑窗切分
    total_lines = len(content.splitlines())
    assert max(c.end_line for c in chunks) == total_lines  # 覆盖到文档末尾，不漏尾
