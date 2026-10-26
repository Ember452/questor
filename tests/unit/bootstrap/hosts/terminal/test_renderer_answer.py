"""`renderer.resolve_answer`：序号映回原文，自由文本照传（plan03 A2）。"""

from __future__ import annotations

from questorharness.bootstrap.hosts.terminal import renderer

OPTIONS = ("保守", "激进", "折中")


def test_number_maps_back_to_the_option_text() -> None:
    assert renderer.resolve_answer("2", OPTIONS) == "激进"


def test_surrounding_whitespace_does_not_break_the_number() -> None:
    assert renderer.resolve_answer("  3  ", OPTIONS) == "折中"


def test_free_text_passes_through_even_with_options() -> None:
    assert renderer.resolve_answer("两个都要", OPTIONS) == "两个都要"


def test_out_of_range_number_is_passed_as_typed() -> None:
    """越界不猜：宁可把原文交给模型，也不替用户选一个选项。"""

    assert renderer.resolve_answer("9", OPTIONS) == "9"


def test_empty_or_missing_answer_is_empty_string() -> None:
    assert renderer.resolve_answer(None, OPTIONS) == ""
    assert renderer.resolve_answer("   ", OPTIONS) == ""


def test_without_options_numbers_are_free_text() -> None:
    assert renderer.resolve_answer("2", ()) == "2"
