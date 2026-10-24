"""Mirror test for ``surfaces/channels/filenames.py`` (plan 01, R7).

Moved out of ``channels/helpers.py`` together with the module itself (ledger #127); the
cases that used to live in ``test_utils/test_helpers.py`` are here, plus the boundaries
that only matter for a name arriving from the network: what comes out must be one
basename, and an unusable name must come out empty so the caller can fall back.
"""

from __future__ import annotations

import pytest

from questorharness.surfaces.channels.filenames import dedupe_filename, safe_filename


def test_path_separators_and_shell_metacharacters_are_removed() -> None:
    assert safe_filename("../bad name;$(rm).txt") == "bad_name_rm_.txt"


@pytest.mark.parametrize("value", ["../", "...", "/", "", None])
def test_an_unusable_name_becomes_empty_rather_than_a_current_directory(value: object) -> None:
    """``.`` and ``..`` are the two names that would escape a directory when joined."""
    assert safe_filename(value) == ""


def test_only_the_basename_of_a_windows_path_survives() -> None:
    assert safe_filename(r"C:\Users\me\Downloads\photo.jpg") == "photo.jpg"


def test_safe_characters_inside_the_name_are_kept() -> None:
    assert safe_filename("a-b_c.2.txt") == "a-b_c.2.txt"


def test_fullwidth_characters_are_normalised_before_filtering() -> None:
    """NFKC first, so a fullwidth latin name is not destroyed by the character class."""
    assert safe_filename("ａｂ-1.txt") == "ab-1.txt"


def test_a_non_ascii_stem_survives_sanitisation() -> None:
    """CJK names are the common case on Feishu, not an attack.

    The ASCII-only character class used to collapse ``"季度报告.pdf"`` to ``"pdf"``: the
    stem became one underscore, the strip removed it together with the dot, and two
    different Chinese attachments in one message then silently overwrote each other.
    Word characters (Unicode) survive; separators, metacharacters and control
    characters still do not.
    """
    assert safe_filename("季度报告.pdf") == "季度报告.pdf"
    assert safe_filename("计划 与执行.md") == "计划_与执行.md"
    assert safe_filename("bad\x00name.txt") == "bad_name.txt"


def test_dedupe_filename_passes_through_when_the_name_is_free() -> None:
    assert dedupe_filename("a.pdf", exists=lambda _name: False) == "a.pdf"


def test_dedupe_filename_appends_a_counter_until_the_name_is_free() -> None:
    taken = {"季度报告.pdf", "季度报告-1.pdf"}
    assert dedupe_filename("季度报告.pdf", exists=taken.__contains__) == "季度报告-2.pdf"


def test_dedupe_filename_handles_names_without_an_extension() -> None:
    taken = {"README"}
    assert dedupe_filename("README", exists=taken.__contains__) == "README-1"


def test_the_result_is_cut_to_the_configured_length() -> None:
    assert len(safe_filename("q" * 200)) == 128
    assert safe_filename("abcdef", max_length=3) == "abc"
