"""Workspace queries built on the Python source index.

Moved out of ``lsp/__init__.py`` by plan 01 W8: this module answers "where is this
defined, what references it, what does hover show". Reading files and parsing
symbols stays in :mod:`python_index`.
"""

from __future__ import annotations

import re
from pathlib import Path

from questorharness.providers.lsp.python_index import (
    SymbolLocation,
    extract_symbol_at_position,
    iter_python_files,
    list_document_symbols,
)


def workspace_symbol_search(root: Path, query: str) -> list[SymbolLocation]:
    """Return symbols whose name contains ``query``."""
    needle = query.lower().strip()
    if not needle:
        return []
    matches: list[SymbolLocation] = []
    for file_path in iter_python_files(root):
        for symbol in list_document_symbols(file_path):
            if needle in symbol.name.lower():
                matches.append(symbol)
    return matches


def go_to_definition(
    *,
    root: Path,
    file_path: Path,
    symbol: str | None = None,
    line: int | None = None,
    character: int | None = None,
) -> list[SymbolLocation]:
    """Resolve candidate definitions for a symbol."""
    target = symbol or extract_symbol_at_position(file_path, line=line, character=character)
    if not target:
        return []
    matches: list[SymbolLocation] = []
    for candidate in iter_python_files(root):
        for item in list_document_symbols(candidate):
            if item.name == target:
                matches.append(item)
    return matches


def find_references(
    *,
    root: Path,
    file_path: Path,
    symbol: str | None = None,
    line: int | None = None,
    character: int | None = None,
) -> list[tuple[Path, int, str]]:
    """Return line-oriented references for a symbol."""
    target = symbol or extract_symbol_at_position(file_path, line=line, character=character)
    if not target:
        return []
    pattern = re.compile(rf"\b{re.escape(target)}\b")
    matches: list[tuple[Path, int, str]] = []
    for candidate in iter_python_files(root):
        for lineno, raw_line in enumerate(candidate.read_text(encoding="utf-8").splitlines(), start=1):
            if pattern.search(raw_line):
                matches.append((candidate, lineno, raw_line.strip()))
    return matches


def hover(
    *,
    root: Path,
    file_path: Path,
    symbol: str | None = None,
    line: int | None = None,
    character: int | None = None,
) -> SymbolLocation | None:
    """Return the best hover target for a symbol."""
    matches = go_to_definition(
        root=root,
        file_path=file_path,
        symbol=symbol,
        line=line,
        character=character,
    )
    return matches[0] if matches else None
