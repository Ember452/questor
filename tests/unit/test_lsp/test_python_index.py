"""Mirror test for ``providers/lsp/python_index.py`` (plan 01, R7).

The index is the read-only half of the lsp helpers: walk files, parse symbols,
resolve an identifier at a cursor position.
"""

from __future__ import annotations

from pathlib import Path

from questorharness.providers.lsp import python_index
from questorharness.providers.lsp.python_index import (
    extract_symbol_at_position,
    iter_python_files,
    list_document_symbols,
)

SAMPLE = '''"""Module doc."""


CONSTANT = 1


class Widget:
    """A widget."""

    def spin(self, speed):
        """Spin fast."""
        return speed


def helper(value):
    """Do work."""
    return value
'''


def _write_sample(root: Path) -> Path:
    path = root / "sample.py"
    path.write_text(SAMPLE, encoding="utf-8")
    return path


def test_list_document_symbols_reports_dotted_names_and_kinds(tmp_path: Path) -> None:
    path = _write_sample(tmp_path)

    symbols = list_document_symbols(path)
    by_name = {symbol.name: symbol for symbol in symbols}

    assert {"CONSTANT", "Widget", "Widget.spin", "helper"} <= set(by_name)
    assert by_name["Widget"].kind == "class"
    assert by_name["Widget.spin"].kind == "function"
    assert by_name["CONSTANT"].kind == "variable"
    assert by_name["helper"].signature == "def helper(value)"
    assert by_name["Widget.spin"].docstring == "Spin fast."
    assert by_name["Widget"].path == path
    assert all(symbol.line > 0 and symbol.character >= 1 for symbol in symbols)


def test_iter_python_files_skips_vendor_dirs_and_sorts(tmp_path: Path) -> None:
    _write_sample(tmp_path)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "aaa.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "ignored.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not python\n", encoding="utf-8")

    found = [path.name for path in iter_python_files(tmp_path)]

    # Order is the sorted full path, so a file at the workspace root sorts before
    # one inside a subdirectory; the contract is "stable", not "by file name".
    assert found == ["sample.py", "aaa.py"]


def test_extract_symbol_at_position_picks_the_identifier_under_cursor(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cursor.py"
    path.write_text("value = compute_thing(x)\n", encoding="utf-8")

    # character is 1-based, so column 10 (index 9) sits inside compute_thing.
    assert extract_symbol_at_position(path, line=1, character=10) == "compute_thing"
    # Index 7 (column 8) is the '=' sign: no identifier contains it, so the
    # documented fallback returns the first identifier on the line.
    assert extract_symbol_at_position(path, line=1, character=8) == "value"


def test_extract_symbol_at_position_edge_cases(tmp_path: Path) -> None:
    path = tmp_path / "edges.py"
    path.write_text("\nalpha = 1\n", encoding="utf-8")

    assert extract_symbol_at_position(path, line=None, character=1) is None
    assert extract_symbol_at_position(path, line=0, character=1) is None
    assert extract_symbol_at_position(path, line=9, character=1) is None
    # Line 1 is blank: no identifier to recover.
    assert extract_symbol_at_position(path, line=1, character=1) is None
    # Past the end of an identifier line, the first identifier is the fallback.
    assert extract_symbol_at_position(path, line=2, character=99) == "alpha"


def test_module_constants_stay_importable_for_siblings() -> None:
    """The skip set is part of the index contract, not an accident of parsing."""
    assert ".venv" in python_index._SKIP_PARTS
    assert python_index._PYTHON_GLOB == "*.py"
