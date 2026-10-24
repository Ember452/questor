"""Mirror test for ``bootstrap/cli/cli_prompts.py`` (plan 01, R7).

Scope note: this module was carved out of the 1190-line CLI entry point, and R7 alone
would have called it covered already -- ``tests/unit/test_questor/test_prompts.py``
shares the shorter stem ``prompts`` but builds system prompts and never imports this
file. Hence the ``cli_prompts`` name and this file. What is covered here is the terminal
interaction layer itself: when a real TTY counts as interactive, what each prompt does
without one, and what happens when the user aborts.
"""

from __future__ import annotations

import sys
import types

import pytest
import typer

from questorharness.bootstrap.cli import cli_prompts
from questorharness.bootstrap.cli.cli_prompts import (
    _AUTH_SOURCE_LABELS,
    _PROVIDER_LABELS,
    _can_use_questionary,
    _confirm_prompt,
    _secret_prompt,
    _select_from_menu,
    _text_prompt,
)

OPTIONS = [("anthropic", "Anthropic (Claude API)"), ("openai", "OpenAI / compatible")]


@pytest.fixture()
def no_questionary(monkeypatch) -> None:
    """Force the "no interactive terminal" branch every non-TTY run already takes."""
    monkeypatch.setattr(cli_prompts, "_can_use_questionary", lambda: False)


@pytest.fixture()
def with_questionary(monkeypatch) -> types.ModuleType:
    """Pretend questionary is installed and interactive, returning a controllable ask()."""
    fake = types.ModuleType("questionary")
    monkeypatch.setitem(sys.modules, "questionary", fake)
    monkeypatch.setattr(cli_prompts, "_can_use_questionary", lambda: True)
    return fake


def test_questionary_is_not_considered_interactive_without_a_tty() -> None:
    # Under pytest the captured streams are not tty-backed, so the plain prompts run.
    assert _can_use_questionary() is False


def test_replaced_streams_are_not_interactive(monkeypatch) -> None:
    class _Tty:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(sys, "stdin", _Tty())
    monkeypatch.setattr(sys, "stdout", _Tty())

    # A redirected or substituted stream is not a terminal a human is looking at.
    assert _can_use_questionary() is False


def test_missing_questionary_package_is_not_interactive(monkeypatch) -> None:
    class _Tty:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(sys, "stdin", sys.__stdin__)
    monkeypatch.setattr(sys, "stdout", sys.__stdout__)
    monkeypatch.setattr(sys.__stdin__, "isatty", lambda: True)
    monkeypatch.setattr(sys.__stdout__, "isatty", lambda: True)
    monkeypatch.setitem(sys.modules, "questionary", None)

    assert _can_use_questionary() is False


def test_text_prompt_falls_back_to_typer_prompt_with_the_default(no_questionary, monkeypatch) -> None:
    seen: list[tuple[str, str]] = []

    def fake_prompt(message: str, *, default: str = "") -> str:
        seen.append((message, default))
        return "typed value"

    monkeypatch.setattr(typer, "prompt", fake_prompt)

    assert _text_prompt("Model", default="claude") == "typed value"
    assert seen == [("Model", "claude")]


def test_secret_prompt_asks_with_input_hidden(no_questionary, monkeypatch) -> None:
    calls: dict[str, object] = {}

    def fake_prompt(message: str, *, hide_input: bool = False) -> str:
        calls["message"] = message
        calls["hide_input"] = hide_input
        return "sk-abc"

    monkeypatch.setattr(typer, "prompt", fake_prompt)

    assert _secret_prompt("Enter API key") == "sk-abc"
    assert calls == {"message": "Enter API key", "hide_input": True}


def test_confirm_prompt_forwards_the_default_and_returns_a_bool(no_questionary, monkeypatch) -> None:
    seen: list[tuple[str, bool]] = []

    def fake_confirm(message: str, *, default: bool = False) -> bool:
        seen.append((message, default))
        return default

    monkeypatch.setattr(typer, "confirm", fake_confirm)

    # A bare question means "no": the safe answer is the default.
    assert _confirm_prompt("Overwrite?") is False
    assert _confirm_prompt("Overwrite?", default=True) is True
    assert seen == [("Overwrite?", False), ("Overwrite?", True)]


def test_menu_prints_numbered_labels_and_marks_the_default(no_questionary, monkeypatch, capsys) -> None:
    monkeypatch.setattr(typer, "prompt", lambda message, *, default="": default)

    result = _select_from_menu("Pick one:", OPTIONS, default_value="openai")

    printed = capsys.readouterr().out
    assert "Pick one:" in printed
    assert "1. Anthropic (Claude API)" in printed
    assert "2. OpenAI / compatible (default)" in printed
    # Nobody answered, so the default index wins.
    assert result == "openai"


def test_menu_respects_a_numbered_choice(no_questionary, monkeypatch) -> None:
    monkeypatch.setattr(typer, "prompt", lambda message, *, default="": "1")

    assert _select_from_menu("Pick one:", OPTIONS) == "anthropic"


def test_menu_rejects_an_unusable_choice(no_questionary, monkeypatch) -> None:
    monkeypatch.setattr(typer, "prompt", lambda message, *, default="": "9")

    with pytest.raises(typer.BadParameter, match="Invalid selection: 9"):
        _select_from_menu("Pick one:", OPTIONS)

    monkeypatch.setattr(typer, "prompt", lambda message, *, default="": "abc")
    with pytest.raises(typer.BadParameter):
        _select_from_menu("Pick one:", OPTIONS)


def test_questionary_abort_is_a_typer_abort(with_questionary, monkeypatch) -> None:
    for name in ("text", "password", "confirm"):
        monkeypatch.setattr(
            with_questionary,
            name,
            lambda *args, **kwargs: types.SimpleNamespace(ask=lambda: None),
            raising=False,
        )
        with pytest.raises(typer.Abort):
            if name == "text":
                _text_prompt("Model")
            elif name == "password":
                _secret_prompt("Key")
            else:
                _confirm_prompt("Sure?")


def test_questionary_selection_returns_its_answer(with_questionary, monkeypatch) -> None:
    monkeypatch.setattr(
        with_questionary,
        "Choice",
        lambda **kwargs: types.SimpleNamespace(**kwargs),
        raising=False,
    )
    monkeypatch.setattr(
        with_questionary,
        "select",
        lambda title, *, choices, default=None: types.SimpleNamespace(ask=lambda: choices[0].value),
        raising=False,
    )
    monkeypatch.setattr(
        with_questionary,
        "text",
        lambda message, *, default="": types.SimpleNamespace(ask=lambda: f"answer:{default}"),
        raising=False,
    )

    assert _select_from_menu("Pick one:", OPTIONS) == "anthropic"
    assert _text_prompt("Model", default="claude") == "answer:claude"


def test_every_provider_and_auth_source_has_a_readable_label() -> None:
    assert _PROVIDER_LABELS and _AUTH_SOURCE_LABELS

    for key, label in {**_PROVIDER_LABELS, **_AUTH_SOURCE_LABELS}.items():
        assert key and "_" not in key[:1], key
        assert label != key
        assert label.strip() == label
        assert "\n" not in label

    # The labels the wizard shows are keyed by the same identifiers settings use.
    assert _PROVIDER_LABELS["anthropic"] == "Anthropic (Claude API)"
    assert _AUTH_SOURCE_LABELS["openai_api_key"] == "OpenAI API key"
