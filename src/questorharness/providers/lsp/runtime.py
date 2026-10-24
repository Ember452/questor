"""LSP runtime adapter implementing the tool-facing port."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from questorharness.providers.lsp import (
    find_references,
    go_to_definition,
    hover,
    list_document_symbols,
    workspace_symbol_search,
)


class ProviderLspRuntime:
    """Adapter over the provider-level LSP helpers."""

    def workspace_symbol_search(self, root: Path, query: str) -> Any:
        return workspace_symbol_search(root, query)

    def list_document_symbols(self, file_path: Path) -> Any:
        return list_document_symbols(file_path)

    def go_to_definition(
        self,
        *,
        root: Path,
        file_path: Path,
        symbol: str | None,
        line: int | None,
        character: int | None,
    ) -> Any:
        return go_to_definition(
            root=root,
            file_path=file_path,
            symbol=symbol,
            line=line,
            character=character,
        )

    def find_references(
        self,
        *,
        root: Path,
        file_path: Path,
        symbol: str | None,
        line: int | None,
        character: int | None,
    ) -> Any:
        return find_references(
            root=root,
            file_path=file_path,
            symbol=symbol,
            line=line,
            character=character,
        )

    def hover(
        self,
        *,
        root: Path,
        file_path: Path,
        symbol: str | None,
        line: int | None,
        character: int | None,
    ) -> Any:
        return hover(
            root=root,
            file_path=file_path,
            symbol=symbol,
            line=line,
            character=character,
        )

# questor: allow R7 -- until W8 adds the mirror test
