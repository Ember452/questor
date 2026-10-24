"""Mirror test for ``surfaces/channels/message_chunks.py`` (plan 01, R7).

Relocated out of ``channels/helpers.py`` with the module split (ledger #127). Chunking is
where a channel hits a platform limit, so the pinned facts are the boundary preference
(newline, then space, then a hard cut), the refusal of a non-positive window, and that no
non-whitespace character is ever lost between chunks.
"""

from __future__ import annotations

import pytest

from questorharness.surfaces.channels.message_chunks import split_message


def test_word_boundaries_are_preferred_over_a_fixed_cut() -> None:
    chunks = split_message("hello world again", 8)

    assert chunks == ["hello", "world", "again"]
    assert all(len(chunk) <= 8 for chunk in chunks)


def test_long_unbroken_text_is_hard_split() -> None:
    assert split_message("abcdef", 2) == ["ab", "cd", "ef"]


def test_a_newline_beats_a_space_inside_the_window() -> None:
    assert split_message("aaa bbb\nccc ddd", 8) == ["aaa bbb", "ccc ddd"]


def test_text_that_fits_is_returned_unchanged() -> None:
    assert split_message("hi", 10) == ["hi"]


def test_empty_text_produces_no_chunks() -> None:
    assert split_message("", 10) == []


@pytest.mark.parametrize("max_length", [0, -3])
def test_a_non_positive_window_is_refused_loudly(max_length: int) -> None:
    """Silently returning nothing here would make a channel drop the message instead."""
    with pytest.raises(ValueError, match="max_length must be positive"):
        split_message("text", max_length)


def test_trailing_whitespace_does_not_become_an_empty_chunk() -> None:
    assert split_message("abc   ", 3) == ["abc"]


def test_a_window_of_only_whitespace_is_kept_verbatim_instead_of_vanishing() -> None:
    """Pinned: when the cut lands on whitespace only, the raw slice is used.

    The alternative (dropping it) would silently discard content the sender wrote.
    """
    assert split_message("\n" * 9 + "abc", 4) == ["\n\n\n\n", "abc"]


@pytest.mark.parametrize(
    "text",
    [
        "line one\nline two\nline three",
        "x" * 50,
        "开头\n" + "中" * 30 + " \n尾",
    ],
)
def test_chunking_never_loses_a_non_whitespace_character(text: str) -> None:
    chunks = split_message(text, 7)

    assert "".join("".join(chunk.split()) for chunk in chunks) == "".join(text.split())
    assert all(len(chunk) <= 7 for chunk in chunks)
