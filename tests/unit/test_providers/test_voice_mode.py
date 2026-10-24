"""Mirror test for ``providers/voice/voice_mode.py`` (plan 01, R7).

Scope note: ``VoiceDiagnostics``/``toggle_voice_mode``/``inspect_voice_capabilities``
were named by no test before this file. The diagnostics function is the only thing
standing between "voice did not start" and a user who has to guess whether the model
or the machine is at fault, so the interesting part is **which** reason wins and **when**
the recorder is still reported.
"""

from __future__ import annotations

import dataclasses

import pytest

from questorharness.providers.llm.provider import ProviderInfo
from questorharness.providers.voice import voice_mode
from questorharness.providers.voice.voice_mode import (
    VoiceDiagnostics,
    inspect_voice_capabilities,
    toggle_voice_mode,
)

NO_RECORDER = "no supported recorder found (expected sox, ffmpeg, or arecord)"


def provider(**overrides: object) -> ProviderInfo:
    base: dict[str, object] = {
        "name": "openai",
        "auth_kind": "api_key",
        "voice_supported": True,
        "voice_reason": "",
    }
    return ProviderInfo(**base | overrides)  # type: ignore[arg-type]


@pytest.fixture()
def recorders(monkeypatch):
    """Control which recorder binaries ``shutil.which`` claims to find."""
    found: dict[str, str] = {}
    monkeypatch.setattr(voice_mode.shutil, "which", lambda exe: found.get(exe))
    return found


def test_toggling_is_a_plain_flip_in_both_directions() -> None:
    assert toggle_voice_mode(True) is False
    assert toggle_voice_mode(False) is True


def test_an_unsupported_provider_wins_even_when_a_recorder_exists(recorders) -> None:
    """The provider's own explanation is used verbatim, and the recorder is still shown."""
    recorders["ffmpeg"] = r"C:\tools\ffmpeg.exe"
    info = provider(voice_supported=False, voice_reason="this provider has no voice shell")

    diag = inspect_voice_capabilities(info)

    assert diag.available is False
    assert diag.reason == "this provider has no voice shell"
    assert diag.recorder == r"C:\tools\ffmpeg.exe"


def test_a_supported_provider_without_a_recorder_reports_no_recorder(recorders) -> None:
    diag = inspect_voice_capabilities(provider())

    assert diag.available is False
    assert diag.reason == NO_RECORDER
    assert diag.recorder is None


def test_a_supported_provider_with_a_recorder_is_available(recorders) -> None:
    recorders["sox"] = "sox"

    diag = inspect_voice_capabilities(provider())

    assert diag.available is True
    assert diag.reason == "voice shell is available"
    assert diag.recorder == "sox"


@pytest.mark.parametrize(
    ("present", "expected"),
    [
        (["sox", "ffmpeg", "arecord"], "sox"),
        (["ffmpeg", "arecord"], "ffmpeg"),
        (["arecord"], "arecord"),
    ],
)
def test_recorder_preference_is_sox_then_ffmpeg_then_arecord(recorders, present, expected) -> None:
    for name in present:
        recorders[name] = name

    assert inspect_voice_capabilities(provider()).recorder == expected


def test_the_recorder_probe_looks_for_exactly_three_binaries(monkeypatch) -> None:
    """The fallback chain is ``sox`` -> ``ffmpeg`` -> ``arecord``, and nothing else.

    A recorder outside that list is invisible to the diagnostics, so installing a
    different tool does not make voice mode available.
    """
    probed: list[str] = []

    def spy(exe: str):
        probed.append(exe)
        return None

    monkeypatch.setattr(voice_mode.shutil, "which", spy)

    diag = inspect_voice_capabilities(provider())

    assert probed == ["sox", "ffmpeg", "arecord"]
    assert diag.available is False


def test_the_summary_is_an_immutable_value_type() -> None:
    diag = VoiceDiagnostics(available=True, reason="voice shell is available")

    assert diag.recorder is None

    with pytest.raises(dataclasses.FrozenInstanceError):
        diag.available = False  # type: ignore[misc]
