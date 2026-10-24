"""Mirror test for ``contracts/tool_outputs.py`` (plan 01, R7).

Scope note: none of the four public names appeared in any test before this file. These
functions are the context budget -- how much of a tool result stays inline, how much
becomes a preview, and which results may be cleared during microcompaction. An
environment variable typo must never turn into "keep zero characters of output", so the
floor-clamp and the invalid-value fallback are the behaviour being pinned.
"""

from __future__ import annotations

import logging

import pytest

from questorharness.contracts.tool_outputs import (
    DEFAULT_MICROCOMPACT_TOOL_RESULT_CHARS,
    DEFAULT_TOOL_OUTPUT_INLINE_CHARS,
    DEFAULT_TOOL_OUTPUT_PREVIEW_CHARS,
    is_microcompactable_tool_result,
    microcompact_tool_result_chars,
    tool_output_inline_chars,
    tool_output_preview_chars,
)

GETTERS = {
    "inline": (tool_output_inline_chars, "QUESTORHARNESS_TOOL_OUTPUT_INLINE_CHARS", DEFAULT_TOOL_OUTPUT_INLINE_CHARS, 256),
    "preview": (tool_output_preview_chars, "QUESTORHARNESS_TOOL_OUTPUT_PREVIEW_CHARS", DEFAULT_TOOL_OUTPUT_PREVIEW_CHARS, 128),
    "microcompact": (
        microcompact_tool_result_chars,
        "QUESTORHARNESS_MICROCOMPACT_TOOL_RESULT_CHARS",
        DEFAULT_MICROCOMPACT_TOOL_RESULT_CHARS,
        256,
    ),
}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch) -> None:
    for _getter, env_name, _default, _minimum in GETTERS.values():
        monkeypatch.delenv(env_name, raising=False)


def test_the_shipped_budgets_are_the_documented_numbers() -> None:
    assert (DEFAULT_TOOL_OUTPUT_INLINE_CHARS, DEFAULT_TOOL_OUTPUT_PREVIEW_CHARS) == (16_000, 3_000)
    assert DEFAULT_MICROCOMPACT_TOOL_RESULT_CHARS == 4_000
    # Nothing is read from the environment when nothing is set.
    assert (tool_output_inline_chars(), tool_output_preview_chars(), microcompact_tool_result_chars()) == (
        16_000,
        3_000,
        4_000,
    )


@pytest.mark.parametrize("name", sorted(GETTERS))
def test_a_raised_limit_is_honoured(name: str, monkeypatch) -> None:
    getter, env, default, _minimum = GETTERS[name]
    monkeypatch.setenv(env, str(default + 1000))

    assert getter() == default + 1000


@pytest.mark.parametrize("raw", ["0", "-40", "1"])
def test_a_value_below_the_floor_is_clamped_up_rather_than_used(raw: str, monkeypatch) -> None:
    for getter, env, _default, minimum in GETTERS.values():
        monkeypatch.setenv(env, raw)
        assert getter() == minimum, (env, raw)


@pytest.mark.parametrize("raw", ["", "   ", "abc", "12.5", "8k"])
def test_an_unparsable_value_falls_back_to_the_default(raw: str, monkeypatch, caplog) -> None:
    for getter, env, default, _minimum in GETTERS.values():
        monkeypatch.setenv(env, raw)
        assert getter() == default, (env, raw)

    if raw.strip():
        with caplog.at_level(logging.WARNING, logger="questorharness.contracts.tool_outputs"):
            microcompact_tool_result_chars()
        assert "Ignoring invalid" in caplog.text


# --- clearing eligibility ------------------------------------------------


def test_a_short_plain_tool_result_is_not_cleared() -> None:
    assert is_microcompactable_tool_result("Read", "short output") is False


def test_a_long_plain_tool_result_becomes_cleared() -> None:
    assert is_microcompactable_tool_result("Bash", "x" * DEFAULT_MICROCOMPACT_TOOL_RESULT_CHARS) is True


def test_exactly_the_threshold_is_enough() -> None:
    content = "y" * (DEFAULT_MICROCOMPACT_TOOL_RESULT_CHARS - 1)
    assert is_microcompactable_tool_result("Bash", content) is False
    assert is_microcompactable_tool_result("Bash", content + "y") is True


def test_mcp_results_are_always_eligible_however_short() -> None:
    assert is_microcompactable_tool_result("mcp__github__issue", "ok") is True
    assert is_microcompactable_tool_result("  mcp__slack__post  ", "") is True


def test_the_clearing_threshold_and_the_reporter_share_one_knob(monkeypatch) -> None:
    monkeypatch.setenv("QUESTORHARNESS_MICROCOMPACT_TOOL_RESULT_CHARS", "4096")

    assert microcompact_tool_result_chars() == 4096
    assert is_microcompactable_tool_result("Bash", "y" * 4_000) is False
    assert is_microcompactable_tool_result("Bash", "y" * 4_096) is True


def test_a_blank_tool_name_is_decided_by_its_content() -> None:
    assert is_microcompactable_tool_result("   ", "short") is False
    assert is_microcompactable_tool_result("", "z" * DEFAULT_MICROCOMPACT_TOOL_RESULT_CHARS) is True
