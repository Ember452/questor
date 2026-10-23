"""Mirror test for ``providers/lsp/symbol_queries.py`` (plan 01, R7).

Covers the query half of the lsp helpers, including the facade re-export the
``lsp`` tool and ``runtime.py`` depend on.
"""

from __future__ import annotations

from pathlib import Path

from questorharness.providers import lsp
from questorharness.providers.lsp import python_index, symbol_queries
from questorharness.providers.lsp.symbol_queries import (
    find_references,
    go_to_definition,
    hover,
    workspace_symbol_search,
)

DEFINITION = '''"""Defines Target."""


class Target:
    """The target class."""

    def run(self):
        """Run it."""
        return 1
'''

USAGE = '''"""Uses Target and a look-alike name."""

from definition import Target

TARGET_LIKE = 1


def use():
    """Instantiate the target."""
    return Target()
'''


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    definition = tmp_path / "definition.py"
    definition.write_text(DEFINITION, encoding="utf-8")
    usage = tmp_path / "usage.py"
    usage.write_text(USAGE, encoding="utf-8")
    return definition, usage


def test_facade_reexports_the_same_objects_as_the_siblings() -> None:
    """Every declared name must resolve to the sibling object, not a copy."""
    for name in lsp.__all__:
        source = getattr(symbol_queries, name, None) or getattr(python_index, name, None)
        assert source is not None, f"{name} is declared but owned by neither sibling"
        assert getattr(lsp, name) is source, name


def test_workspace_symbol_search_is_case_insensitive_substring(tmp_path: Path) -> None:
    _workspace(tmp_path)

    names = {symbol.name for symbol in workspace_symbol_search(tmp_path, "TARGET")}

    assert {"Target", "TARGET_LIKE"} <= names


def test_workspace_symbol_search_ignores_a_blank_query(tmp_path: Path) -> None:
    _workspace(tmp_path)
    assert workspace_symbol_search(tmp_path, "   ") == []


def test_go_to_definition_matches_by_name(tmp_path: Path) -> None:
    definition, usage = _workspace(tmp_path)

    matches = go_to_definition(root=tmp_path, file_path=usage, symbol="Target")

    assert [item.path for item in matches] == [definition]
    assert matches[0].kind == "class"


def test_go_to_definition_resolves_the_symbol_under_the_cursor(tmp_path: Path) -> None:
    definition, usage = _workspace(tmp_path)

    # usage.py line 3 is "from definition import Target"; the identifier spans
    # 1-based columns 24-29, so column 24 resolves the cursor onto it (column 19
    # would land on ``import`` and resolve nothing).
    matches = go_to_definition(root=tmp_path, file_path=usage, line=3, character=24)

    assert [item.path for item in matches] == [definition]
    assert go_to_definition(root=tmp_path, file_path=usage, line=3, character=19) == []


def test_go_to_definition_returns_nothing_for_an_unknown_symbol(tmp_path: Path) -> None:
    _, usage = _workspace(tmp_path)
    assert go_to_definition(root=tmp_path, file_path=usage, symbol="NoSuchThing") == []


def test_find_references_uses_word_boundaries(tmp_path: Path) -> None:
    _, usage = _workspace(tmp_path)

    found = find_references(root=tmp_path, file_path=usage, symbol="Target")
    hits = {(path.name, line) for path, line, _text in found}

    # "from definition import Target" (line 3) and "return Target()" (line 10).
    assert ("usage.py", 3) in hits
    assert ("usage.py", 10) in hits
    # TARGET_LIKE on line 5 is a different identifier and must not match, and the
    # lowercase "target" in a docstring must not match either.
    assert ("usage.py", 5) not in hits
    assert ("usage.py", 9) not in hits
    assert all(text for _path, _line, text in found)


def test_hover_returns_the_first_candidate_or_none(tmp_path: Path) -> None:
    definition, usage = _workspace(tmp_path)

    located = hover(root=tmp_path, file_path=usage, symbol="Target")

    assert located is not None
    assert located.path == definition
    assert hover(root=tmp_path, file_path=usage, symbol="Absent") is None
