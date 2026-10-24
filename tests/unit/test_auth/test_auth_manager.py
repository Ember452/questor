"""Mirror test for ``providers/auth/auth_manager.py`` (plan 01, R7).

Scope note: the CLI and gateway tests construct an ``AuthManager`` but never assert on
it. This file covers the manager's own contract, which had no test: lazy settings, the
profile read/write surface, the guard rails that refuse a destructive switch, and the
rule that a stored api_key is mirrored back into the flat settings snapshot.
Persistence is stubbed — this is about the manager's decisions, not the keyring.
"""

from __future__ import annotations

import pytest

from questorharness.config.settings import (
    ProviderProfile,
    Settings,
    auth_source_provider_name,
    builtin_provider_profile_names,
)
from questorharness.providers.auth import auth_manager as auth_manager_module
from questorharness.providers.auth.auth_manager import AuthManager


@pytest.fixture()
def saved(monkeypatch) -> list[Settings]:
    """Capture every persist instead of touching the real settings file."""
    calls: list[Settings] = []
    monkeypatch.setattr("questorharness.config.save_settings", lambda settings: calls.append(settings))
    return calls


@pytest.fixture()
def manager(saved: list[Settings]) -> AuthManager:
    return AuthManager(Settings())


def _profile(**overrides) -> ProviderProfile:
    kwargs = {
        "label": "Custom",
        "provider": "openai",
        "api_format": "openai",
        "auth_source": "openai_api_key",
        "default_model": "gpt-test",
    }
    kwargs.update(overrides)
    return ProviderProfile(**kwargs)


def test_settings_are_loaded_only_when_asked(monkeypatch) -> None:
    loaded: list[int] = []

    def _fake_load():
        loaded.append(1)
        return Settings(model="late-loaded")

    monkeypatch.setattr("questorharness.config.load_settings", _fake_load)
    manager = AuthManager()

    assert loaded == []
    assert manager.settings.model == "late-loaded"
    assert manager.settings.model == "late-loaded"
    assert loaded == [1]


def test_an_injected_settings_object_is_used_as_is(saved: list[Settings]) -> None:
    settings = Settings()

    assert AuthManager(settings).settings is settings


def test_active_profile_and_provider_come_from_settings(manager: AuthManager) -> None:
    name, profile = manager.settings.resolve_profile()

    assert manager.get_active_profile() == name
    assert manager.get_active_provider() == profile.provider


def test_list_profiles_returns_the_merged_catalog(manager: AuthManager) -> None:
    profiles = manager.list_profiles()

    assert profiles
    assert all(isinstance(profile, ProviderProfile) for profile in profiles.values())
    assert set(builtin_provider_profile_names()) <= set(profiles)


def test_activating_an_unknown_profile_is_refused_without_writing(manager: AuthManager, saved) -> None:
    with pytest.raises(ValueError, match="Unknown provider profile"):
        manager.use_profile("nope")

    assert saved == []


def test_upsert_then_use_profile_persists_once_each(manager: AuthManager, saved) -> None:
    manager.upsert_profile("mine", _profile())

    assert manager.get_active_profile() == "claude-api"
    assert "mine" in manager.list_profiles()

    manager.use_profile("mine")

    assert manager.get_active_profile() == "mine"
    assert manager.get_active_provider() == "openai"
    assert len(saved) == 2


def test_upsert_replaces_an_existing_profile(manager: AuthManager, saved) -> None:
    manager.upsert_profile("mine", _profile(default_model="first"))
    manager.upsert_profile("mine", _profile(default_model="second"))

    assert manager.list_profiles()["mine"].default_model == "second"
    assert len(saved) == 2


def test_update_only_changes_the_fields_named_by_the_caller(manager: AuthManager, saved) -> None:
    manager.upsert_profile("mine", _profile(base_url="https://a", context_window_tokens=8000))
    before = manager.list_profiles()["mine"]

    manager.update_profile("mine", default_model="gpt-next")

    after = manager.list_profiles()["mine"]
    assert after.default_model == "gpt-next"
    assert (after.base_url, after.context_window_tokens) == (before.base_url, before.context_window_tokens)
    assert after.credential_slot == before.credential_slot


def test_an_optional_field_cannot_be_cleared_through_update(manager: AuthManager, saved) -> None:
    # ``None`` means "not supplied" for every optional argument, so passing it on purpose
    # does not erase the stored value. Pinned because callers reading the signature alone
    # would assume the opposite, and this surface has no reset-to-default path.
    manager.upsert_profile("mine", _profile(base_url="https://a"))

    manager.update_profile("mine", base_url=None)

    assert manager.list_profiles()["mine"].base_url == "https://a"


def test_update_rejects_an_unknown_profile(manager: AuthManager, saved) -> None:
    with pytest.raises(ValueError, match="Unknown provider profile"):
        manager.update_profile("ghost", default_model="x")

    assert saved == []


def test_the_active_profile_cannot_be_removed(manager: AuthManager, saved) -> None:
    with pytest.raises(ValueError, match="Cannot remove the active profile"):
        manager.remove_profile(manager.get_active_profile())

    assert saved == []


def test_a_built_in_profile_cannot_be_removed(manager: AuthManager, saved) -> None:
    active = manager.get_active_profile()
    builtin = next(
        name for name in manager.list_profiles() if name in builtin_provider_profile_names() and name != active
    )

    with pytest.raises(ValueError, match="Cannot remove built-in profile"):
        manager.remove_profile(builtin)

    assert builtin in manager.list_profiles()


def test_removing_an_unknown_profile_is_refused(manager: AuthManager, saved) -> None:
    with pytest.raises(ValueError, match="Unknown provider profile"):
        manager.remove_profile("ghost")


def test_a_custom_profile_can_be_removed(manager: AuthManager, saved) -> None:
    manager.upsert_profile("mine", _profile())

    manager.remove_profile("mine")

    assert "mine" not in manager.list_profiles()
    assert manager.get_active_profile() == "claude-api"


def test_switching_auth_source_validates_the_name(manager: AuthManager, saved) -> None:
    with pytest.raises(ValueError, match="Unknown auth source"):
        manager.switch_auth_source("carrier_pigeon")

    manager.switch_auth_source("openai_api_key", profile_name="claude-api")

    assert manager.list_profiles()["claude-api"].auth_source == "openai_api_key"
    assert saved


def test_switch_provider_accepts_sources_profiles_and_provider_names(manager: AuthManager, saved) -> None:
    with pytest.raises(ValueError, match="Unknown provider or auth source"):
        manager.switch_provider("not-a-provider")

    # An auth-source switch rewires the *active* profile's auth_source and leaves it on
    # the same provider; it is not a way to move between providers.
    manager.switch_provider("codex_subscription")
    assert manager.get_active_profile() == "claude-api"
    assert manager.list_profiles()["claude-api"].auth_source == "codex_subscription"

    manager.switch_provider("gemini")
    assert manager.get_active_profile() == "gemini"
    assert manager.get_active_provider() == "gemini"


def test_switch_provider_routes_a_profile_name_to_use_profile(manager: AuthManager, saved) -> None:
    manager.upsert_profile("mine", _profile())

    manager.switch_provider("mine")

    assert manager.get_active_profile() == "mine"


def test_storing_an_api_key_mirrors_it_into_the_flat_snapshot(manager: AuthManager, saved, monkeypatch) -> None:
    stored: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        auth_manager_module,
        "store_credential",
        lambda provider, key, value: stored.append((provider, key, value)),
    )
    active = manager.list_profiles()[manager.get_active_profile()]
    provider = auth_source_provider_name(active.auth_source)

    manager.store_credential(provider, "api_key", "sk-live")

    assert stored == [(provider, "api_key", "sk-live")]
    assert manager.settings.api_key == "sk-live"


def test_another_providers_key_does_not_touch_the_snapshot(manager: AuthManager, saved, monkeypatch) -> None:
    stored: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        auth_manager_module,
        "store_credential",
        lambda provider, key, value: stored.append((provider, key, value)),
    )

    manager.store_credential("someone-else", "api_key", "sk-other")

    assert stored
    assert manager.settings.api_key == ""


def test_clearing_the_active_provider_also_blanks_the_snapshot(manager: AuthManager, saved, monkeypatch) -> None:
    cleared: list[str] = []
    monkeypatch.setattr(auth_manager_module, "store_credential", lambda *args: None)
    monkeypatch.setattr(auth_manager_module, "clear_provider_credentials", lambda provider: cleared.append(provider))
    active = manager.list_profiles()[manager.get_active_profile()]
    provider = auth_source_provider_name(active.auth_source)

    manager.store_credential(provider, "api_key", "sk-live")
    manager.clear_credential(provider)

    assert cleared == [provider]
    assert manager.settings.api_key == ""


def test_profile_credentials_need_a_known_profile(manager: AuthManager, monkeypatch) -> None:
    monkeypatch.setattr(auth_manager_module, "store_credential", lambda *args: None)

    with pytest.raises(ValueError, match="Unknown provider profile"):
        manager.store_profile_credential("ghost", "api_key", "sk")
    with pytest.raises(ValueError, match="Unknown provider profile"):
        manager.clear_profile_credential("ghost")


def test_profile_credentials_are_stored_under_the_provider_namespace(
    manager: AuthManager, saved, monkeypatch
) -> None:
    stored: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        auth_manager_module,
        "store_credential",
        lambda provider, key, value: stored.append((provider, key, value)),
    )
    manager.upsert_profile("mine", _profile())

    manager.store_profile_credential("mine", "api_key", "sk-mine")

    # A profile without a credential_slot shares the provider-level store, so two
    # profiles on one provider overwrite each other's key by design.
    assert stored == [("openai", "api_key", "sk-mine")]
    # A non-active profile must not leak into the flat settings snapshot.
    assert manager.settings.api_key == ""


def test_a_credential_slot_binds_the_profile_to_its_own_namespace(
    manager: AuthManager, saved, monkeypatch
) -> None:
    stored: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        auth_manager_module,
        "store_credential",
        lambda provider, key, value: stored.append((provider, key, value)),
    )
    manager.upsert_profile("mine", _profile(credential_slot="tenant-a"))

    manager.store_profile_credential("mine", "api_key", "sk-mine")

    assert stored == [("profile:tenant-a", "api_key", "sk-mine")]


def test_the_active_profile_key_is_mirrored_into_the_snapshot(manager: AuthManager, saved, monkeypatch) -> None:
    stored: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        auth_manager_module,
        "store_credential",
        lambda provider, key, value: stored.append((provider, key, value)),
    )
    active = manager.get_active_profile()

    manager.store_profile_credential(active, "api_key", "sk-active")

    assert manager.settings.api_key == "sk-active"
    assert saved
