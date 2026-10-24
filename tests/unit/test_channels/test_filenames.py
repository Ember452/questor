"""Mirror test for ``surfaces/channels/filenames.py`` (plan 01, R7).

Moved out of ``channels/helpers.py`` together with the module itself (ledger #127); the
cases that used to live in ``test_utils/test_helpers.py`` are here, plus the boundaries
that only matter for a name arriving from the network: what comes out must be one
basename, and an unusable name must come out empty so the caller can fall back.
"""

from __future__ import annotations

import pytest

from questorharness.surfaces.channels.filenames import safe_filename


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


def test_a_non_ascii_stem_leaves_only_the_extension_behind() -> None:
    """Pinned, not blessed: the dot is a safe character, the CJK stem is not.

    ``"季度报告.pdf"`` becomes ``"pdf"`` -- the stem collapses to a single underscore that
    the strip then removes, so what is left reads like a name without an extension. The
    Feishu adapter only checks for an *empty* result, so this value is used as-is.
    """
    assert safe_filename("季度报告.pdf") == "pdf"


def test_the_result_is_cut_to_the_configured_length() -> None:
    assert len(safe_filename("q" * 200)) == 128
    assert safe_filename("abcdef", max_length=3) == "abc"
