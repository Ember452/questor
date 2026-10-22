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


def test_broadly_named_credentials_are_scrubbed() -> None:
    """#159：非规范命名的凭据（AWS/GH/STRIPE/DB）必须被擦，而普通词不误伤。"""
    _scrubbed, names = scrub_environment(
        {
            "AWS_ACCESS_KEY_ID": "AKIAxx",
            "GH_PAT": "ghp_xx",
            "STRIPE_KEY": "sk_xx",
            "DB_PASSWORD": "p",
            "MY_TLS_CLIENT_SECRET": "s",
            "MONKEY": "keep-me",
            "PATHOGEN": "keep-me",
            "REPEAT_COUNT": "keep-me",
        }
    )
    got = set(names)
    assert {"AWS_ACCESS_KEY_ID", "GH_PAT", "STRIPE_KEY", "DB_PASSWORD", "MY_TLS_CLIENT_SECRET"} <= got, f"漏擦：{got}"
    assert not ({"MONKEY", "PATHOGEN", "REPEAT_COUNT"} & got), f"误伤普通词：{got}"


def test_plural_credential_keys_are_scrubbed() -> None:
    """W6-003：复数命名的凭据键（..._API_KEYS / ..._TOKENS）必须被擦，且不误伤普通复数词。"""
    _scrubbed, names = scrub_environment(
        {
            "QUESTOR_OPENAI_API_KEYS": "a,b",
            "MY_ACCESS_TOKENS": "t",
            "MONKEYS": "keep-me",
            "SYSTEMS": "keep-me",
        }
    )
    got = set(names)
    assert "QUESTOR_OPENAI_API_KEYS" in got, f"复数键漏擦：{got}"
    assert "MY_ACCESS_TOKENS" in got, f"复数 TOKENS 漏擦：{got}"
    assert not ({"MONKEYS", "SYSTEMS"} & got), f"误伤普通词：{got}"
