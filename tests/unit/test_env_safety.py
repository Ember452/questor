"""Provider credential 与 subprocess env scrub（ADR-0018）。"""

from __future__ import annotations

import os

import pytest

from questor.providers.env_safety import build_child_env, is_provider_credential, scrub_environment


def test_provider_credentials_are_never_passthrough_registerable() -> None:
    assert is_provider_credential("LITELLM_API_KEY")
    assert is_provider_credential("openai_api_key")
    assert is_provider_credential("QUESTOR_MODEL_API_KEY")


def test_third_party_credentials_can_be_declared_but_still_scrubbed_by_default(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(os, "environ", {"TENOR_API_KEY": "third-party", "PATH": os.environ["PATH"]})
    scrubbed, _names = scrub_environment()
    assert "TENOR_API_KEY" not in scrubbed
    built = build_child_env(scrubbed, declared=("TENOR_API_KEY",))
    assert built["TENOR_API_KEY"] == os.environ["TENOR_API_KEY"]


def test_provider_declared_env_always_denied(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(os, "environ", {"OPENAI_API_KEY": "secret", "PATH": os.environ["PATH"]})
    with pytest.raises(PermissionError, match="provider credential"):
        build_child_env(scrub_environment()[0], declared=("OPENAI_API_KEY",))


def test_ambient_path_and_locale_survive_scrub(monkeypatch) -> None:  # noqa: ANN001
    values = {"PATH": "C:\\x", "HOME": "/tmp", "LANG": "en_US.UTF-8", "HTTPS_PROXY": "http://127.0.0.1:8", "OPENAI_API_KEY": "secret"}
    monkeypatch.setattr(os, "environ", values)
    result, _names = scrub_environment()
    assert result["PATH"] == "C:\\x"
    assert result["HOME"] == "/tmp"
    assert result["LANG"] == "en_US.UTF-8"
    assert result["HTTPS_PROXY"] == "http://127.0.0.1:8"
    assert "OPENAI_API_KEY" not in result


def test_scrubbed_names_exclude_values() -> None:
    scrubbed, names = scrub_environment({"LITELLM_API_KEY": "do-not-leak"})
    assert scrubbed == {}
    assert names == ("LITELLM_API_KEY",)
    assert "do-not-leak" not in str(names)
