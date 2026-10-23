"""Lightweight code-intelligence helpers for the ``lsp`` tool.

This is intentionally smaller than a full language-server integration. It
provides stable read-only operations for Python source files so the model can
perform definition, reference, hover, and symbol queries in a Claude
Code-like workflow.

Facade only (ADR-0003 §2): reading and parsing lives in ``python_index``,
workspace queries in ``symbol_queries``.
"""

from __future__ import annotations

from questorharness.providers.lsp.python_index import (
    SymbolLocation,
    extract_symbol_at_position,
    iter_python_files,
    list_document_symbols,
)
from questorharness.providers.lsp.symbol_queries import (
    find_references,
    go_to_definition,
    hover,
    workspace_symbol_search,
)

__all__ = [
    "SymbolLocation",
    "extract_symbol_at_position",
    "find_references",
    "go_to_definition",
    "hover",
    "iter_python_files",
    "list_document_symbols",
    "workspace_symbol_search",
]
