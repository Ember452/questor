"""Python source index for the lightweight ``lsp`` helpers.

Moved out of ``lsp/__init__.py`` by plan 01 W8: this module answers "what symbols
exist in this file and where are the files". No query logic lives here.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

_PYTHON_GLOB = "*.py"
_SKIP_PARTS = {".git", ".hg", ".svn", ".venv", "venv", "__pycache__", "node_modules"}


@dataclass(frozen=True)
class SymbolLocation:
    """Resolved symbol location inside the workspace."""

    name: str
    kind: str
    path: Path
    line: int
    character: int
    signature: str = ""
    docstring: str = ""


def list_document_symbols(path: Path) -> list[SymbolLocation]:
    """Return top-level and nested symbols from one Python source file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    symbols: list[SymbolLocation] = []
    _collect_symbols(tree, path, symbols, parent=None)
    return symbols


def extract_symbol_at_position(
    file_path: Path,
    *,
    line: int | None,
    character: int | None,
) -> str | None:
    """Extract a probable identifier from a 1-based line/character position."""
    if line is None:
        return None
    lines = file_path.read_text(encoding="utf-8").splitlines()
    if line < 1 or line > len(lines):
        return None
    text = lines[line - 1]
    if not text:
        return None
    index = max(0, min((character or 1) - 1, len(text) - 1))
    for match in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*", text):
        if match.start() <= index < match.end():
            return match.group(0)
    for match in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*", text):
        return match.group(0)
    return None


def iter_python_files(root: Path) -> list[Path]:
    """Return Python source files in a stable order."""
    files: list[Path] = []
    for path in root.rglob(_PYTHON_GLOB):
        if any(part in _SKIP_PARTS for part in path.parts):
            continue
        if path.is_file():
            files.append(path)
    files.sort()
    return files


def _collect_symbols(
    node: ast.AST,
    path: Path,
    bucket: list[SymbolLocation],
    *,
    parent: str | None,
) -> None:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = f"{parent}.{child.name}" if parent else child.name
            args = [arg.arg for arg in child.args.args]
            signature = f"def {child.name}({', '.join(args)})"
            bucket.append(
                SymbolLocation(
                    name=name,
                    kind="function",
                    path=path,
                    line=child.lineno,
                    character=child.col_offset + 1,
                    signature=signature,
                    docstring=ast.get_docstring(child) or "",
                )
            )
            _collect_symbols(child, path, bucket, parent=name)
        elif isinstance(child, ast.ClassDef):
            name = f"{parent}.{child.name}" if parent else child.name
            bucket.append(
                SymbolLocation(
                    name=name,
                    kind="class",
                    path=path,
                    line=child.lineno,
                    character=child.col_offset + 1,
                    signature=f"class {child.name}",
                    docstring=ast.get_docstring(child) or "",
                )
            )
            _collect_symbols(child, path, bucket, parent=name)
        elif isinstance(child, ast.Assign):
            for target in child.targets:
                if isinstance(target, ast.Name):
                    name = f"{parent}.{target.id}" if parent else target.id
                    bucket.append(
                        SymbolLocation(
                            name=name,
                            kind="variable",
                            path=path,
                            line=target.lineno,
                            character=target.col_offset + 1,
                            signature=f"{target.id} = ...",
                        )
                    )
        else:
            _collect_symbols(child, path, bucket, parent=parent)
