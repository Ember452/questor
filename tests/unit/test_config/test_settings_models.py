"""Mirror test for the decision functions in ``config/settings_models.py`` (plan 01, R7).

Scope note: the model/profile/auth helpers below were named by no test at all --
``resolve_model_setting``, ``is_claude_family_provider``, ``auth_source_uses_api_key``,
``auth_source_env_var_candidates``, ``resolve_auth_env_value``,
``credential_storage_provider_name``, ``display_label_for_profile``. They decide which
model id a user's alias becomes, and where a credential is stored, so a regression here
either silently changes which model answers or reads a key from the wrong namespace.
The rest of the file (the pydantic models) is exercised through Settings elsewhere.
"""

from __future__ import annotations

import pytest

from questorharness.config.settings import (
    ProviderProfile,
    auth_source_env_var_candidates,
    auth_source_uses_api_key,
    credential_storage_provider_name,
    default_provider_profiles,
    display_label_for_profile,
    is_claude_family_provider,
    normalize_anthropic_model_name,
    resolve_auth_env_value,
    resolve_model_setting,
)


def profile(**overrides) -> ProviderProfile:
    base = {
        "label": "Tenant",
        "provider": "openai",
        "api_format": "openai",
        "auth_source": "openai_api_key",
        "default_model": "gpt-4o",
    }
    return ProviderProfile(**(base | overrides))


# --- provider families ----------------------------------------------------


@pytest.mark.parametrize("provider", ["anthropic", "anthropic_claude"])
def test_the_claude_family_covers_both_api_and_subscription_providers(provider: str) -> None:
    assert is_claude_family_provider(provider) is True


@pytest.mark.parametrize("provider", ["openai", "openai_codex", "copilot", "gemini", "", "Anthropic"])
def test_the_family_check_is_exact_and_case_sensitive(provider: str) -> None:
    """Pinned: an uppercase provider is not the claude family.

    Callers pass provider ids from settings/enums, never free text, so being strict is
    the safe direction -- but it means nobody may normalise case before this check.
    """
    assert is_claude_family_provider(provider) is False


# --- model aliases --------------------------------------------------------


def test_a_bare_alias_becomes_the_concrete_claude_model() -> None:
    assert resolve_model_setting("sonnet", "anthropic") == "claude-sonnet-4-6"
    assert resolve_model_setting("opus", "anthropic") == "claude-opus-4-6"
    assert resolve_model_setting("haiku", "anthropic_claude") == "claude-haiku-4-5"
    assert resolve_model_setting("sonnet[1m]", "anthropic") == "claude-sonnet-4-6[1m]"


def test_aliases_are_matched_case_insensitively_and_trimmed() -> None:
    assert resolve_model_setting("  OPUS  ", "anthropic") == "claude-opus-4-6"


def test_best_prefers_the_strongest_model_for_the_family() -> None:
    assert resolve_model_setting("best", "anthropic") == "claude-opus-4-6"
    assert resolve_model_setting("best", "openai") == "gpt-5.4"
    assert resolve_model_setting("default", "copilot") == "gpt-5.4"


def test_opusplan_only_goes_opus_while_plan_mode_is_active() -> None:
    assert resolve_model_setting("opusplan", "anthropic", permission_mode="plan") == "claude-opus-4-6"
    assert resolve_model_setting("opusplan", "anthropic", permission_mode="acceptEdits") == "claude-sonnet-4-6"
    assert resolve_model_setting("opusplan", "anthropic") == "claude-sonnet-4-6"


def test_an_unknown_claude_value_is_normalised_rather_than_passed_through_raw() -> None:
    assert resolve_model_setting("anthropic/claude-sonnet-4.6", "anthropic") == "claude-sonnet-4-6"
    assert resolve_model_setting("claude-sonnet-4.6", "anthropic") == "claude-sonnet-4-6"
    # a non-claude name is left alone apart from trimming
    assert resolve_model_setting(" llama-3 ", "anthropic") == "llama-3"


def test_normalisation_only_rewrites_dots_for_claude_names() -> None:
    assert normalize_anthropic_model_name("anthropic/claude-opus-4.1") == "claude-opus-4.1".replace(".", "-")
    assert normalize_anthropic_model_name("mistral.large") == "mistral.large"
    assert normalize_anthropic_model_name(" CLAUDE-X.Y ") == "CLAUDE-X-Y"


def test_openai_style_aliases_are_left_as_written_when_not_special() -> None:
    assert resolve_model_setting("gpt-4o-mini", "openai") == "gpt-4o-mini"
    # "best" is special only for the providers that have no tiered family
    assert resolve_model_setting("best", "moonshot") == "best"


def test_an_empty_setting_uses_the_profile_default_then_the_provider_family() -> None:
    assert resolve_model_setting("", "anthropic", default_model="haiku") == "claude-haiku-4-5"
    assert resolve_model_setting("default", "openai", default_model="gpt-4o") == "gpt-4o"
    assert resolve_model_setting("", "openai") == "gpt-5.4"
    assert resolve_model_setting("", "anthropic") == "claude-sonnet-4-6"


def test_a_default_that_is_itself_the_word_default_does_not_recurse() -> None:
    assert resolve_model_setting("", "openai", default_model="DEFAULT") == "gpt-5.4"
    assert resolve_model_setting("  ", "anthropic", default_model="default") == "claude-sonnet-4-6"


# --- auth sources ---------------------------------------------------------


@pytest.mark.parametrize("source", ["anthropic_api_key", "openai_api_key", "modelscope_api_key"])
def test_api_key_sources_are_the_ones_a_user_pastes_a_secret_into(source: str) -> None:
    assert auth_source_uses_api_key(source) is True


@pytest.mark.parametrize("source", ["claude_subscription", "codex_subscription", "copilot_oauth", "", "api_key_prefix"])
def test_subscriptions_and_oauth_are_not_api_key_sources(source: str) -> None:
    assert auth_source_uses_api_key(source) is False


def test_env_candidates_are_ordered_product_var_first() -> None:
    assert auth_source_env_var_candidates("anthropic_api_key") == (
        "QUESTORHARNESS_ANTHROPIC_API_KEY",
        "ANTHROPIC_API_KEY",
    )
    assert auth_source_env_var_candidates("claude_subscription") == ()


def test_the_first_non_empty_env_var_wins(monkeypatch) -> None:
    monkeypatch.delenv("QUESTORHARNESS_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-shell")

    assert resolve_auth_env_value("anthropic_api_key") == ("ANTHROPIC_API_KEY", "sk-from-shell")

    monkeypatch.setenv("QUESTORHARNESS_ANTHROPIC_API_KEY", "sk-override")
    assert resolve_auth_env_value("anthropic_api_key") == ("QUESTORHARNESS_ANTHROPIC_API_KEY", "sk-override")

    monkeypatch.setenv("QUESTORHARNESS_ANTHROPIC_API_KEY", "")
    assert resolve_auth_env_value("anthropic_api_key") == ("ANTHROPIC_API_KEY", "sk-from-shell")


def test_a_source_without_candidates_or_with_an_empty_environment_resolves_to_none(monkeypatch) -> None:
    for name in auth_source_env_var_candidates("openai_api_key"):
        monkeypatch.delenv(name, raising=False)

    assert resolve_auth_env_value("openai_api_key") is None
    assert resolve_auth_env_value("gemini_api_key") is None


# --- credential namespaces ------------------------------------------------


def test_a_builtin_profile_shares_the_provider_level_namespace() -> None:
    builtin = default_provider_profiles()["openai-compatible"]

    assert credential_storage_provider_name("openai-compatible", builtin) == "openai"


def test_a_compatible_gateway_with_its_own_slot_gets_an_isolated_namespace() -> None:
    custom = profile(auth_source="openai_api_key", credential_slot="tenant-a")

    assert credential_storage_provider_name("mine", custom) == "profile:tenant-a"


def test_a_slot_on_a_subscription_profile_does_not_isolate_anything() -> None:
    """Pinned: only API-key sources honour the slot.

    A subscription is bound by the external CLI, so a slot would create a namespace
    nothing ever reads.
    """
    subscription = profile(auth_source="claude_subscription", credential_slot="work")

    assert credential_storage_provider_name("mine", subscription) == "anthropic_claude"


def test_the_profile_name_is_not_part_of_the_namespace_key() -> None:
    """Pinned: renaming a profile keeps pointing at the same stored credential."""
    shared = profile(auth_source="openai_api_key")

    assert credential_storage_provider_name("first", shared) == credential_storage_provider_name("second", shared)


# --- labels --------------------------------------------------------------


def test_a_builtin_profile_always_shows_the_current_catalog_label() -> None:
    name = "claude-api"
    stale = default_provider_profiles()[name].model_copy(update={"label": "Ancient wording"})

    assert display_label_for_profile(name, stale) == default_provider_profiles()[name].label
    assert display_label_for_profile("custom-one", profile(label="My gateway")) == "My gateway"
