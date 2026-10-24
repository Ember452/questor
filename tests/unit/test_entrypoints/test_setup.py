"""Mirror test for ``bootstrap/cli/setup.py`` (plan 01, R7).

Scope note: ``test_main.py`` drives the whole wizard through the Typer runner with the
prompts stubbed, which proves the flow but not the decisions. This file pins the
decisions: what a workflow label looks like when auth is missing, which profile each
family choice creates, that an empty answer is refused instead of being silently
written, and that the message a user reads before a key is entered is built from the
auth-source label table -- the observer row 103 said was missing.
"""

from __future__ import annotations

import sys
import types

import pytest
import typer

from questorharness.bootstrap.cli import setup
from questorharness.bootstrap.cli.setup import (
    _configure_custom_profile_via_setup,
    _ensure_preset_profile,
    _ensure_profile_auth,
    _format_profile_choice_label,
    _maybe_update_profile_auth,
    _prompt_api_key_for_profile,
    _select_setup_workflow,
    _specialize_setup_target,
    _styled_missing_suffix,
    setup_cmd,
)
from questorharness.config.settings import ProviderProfile

STATUSES = {
    "claude-api": {
        "label": "Claude API",
        "configured": True,
        "auth_state": "ready",
        "auth_source": "anthropic_api_key",
    },
    "openai-compatible": {
        "label": "OpenAI",
        "configured": False,
        "auth_state": "missing auth",
        "auth_source": "openai_api_key",
    },
    "custom": {
        "label": "Custom",
        "configured": False,
        "auth_state": "missing auth",
        "auth_source": "openai_api_key",
    },
}


def _profile(**kwargs) -> ProviderProfile:
    base = {
        "label": "P",
        "provider": "openai",
        "api_format": "openai",
        "auth_source": "openai_api_key",
        "default_model": "gpt-test",
    }
    return ProviderProfile(**(base | kwargs))


class _Manager:
    """Stands in for AuthManager: same call surface, every call recorded."""

    def __init__(self, statuses=None, profiles=None):
        self.statuses = dict(STATUSES) if statuses is None else dict(statuses)
        self.profiles = dict(profiles or {})
        self.upserts: list[tuple[str, ProviderProfile]] = []
        self.stored: list[tuple[str, str, str]] = []
        self.updated: list[tuple[str, dict]] = []
        self.activated: list[str] = []

    def get_profile_statuses(self):
        return self.statuses

    def get_active_profile(self):
        return "claude-api"

    def list_profiles(self):
        return self.profiles

    def upsert_profile(self, name, profile):
        self.upserts.append((name, profile))
        self.profiles[name] = profile

    def store_profile_credential(self, name, key, value):
        self.stored.append((name, key, value))

    def update_profile(self, name, **kwargs):
        self.updated.append((name, kwargs))

    def use_profile(self, name):
        self.activated.append(name)


class _Flow:
    """Stands in for ApiKeyFlow, which the wizard imports inside the function body."""

    last_prompt = ""
    result = "sk-from-flow"
    error: Exception | None = None

    def __init__(self, *, provider: str, prompt_text: str) -> None:
        type(self).last_prompt = prompt_text
        self.provider = provider

    def run(self) -> str:
        if type(self).error is not None:
            raise type(self).error
        return type(self).result


@pytest.fixture()
def menu(monkeypatch) -> list:
    """Capture the menu the wizard would show and answer with its first choice."""
    recorded: list[tuple[str, list[tuple[str, str]], str | None]] = []

    def fake(title, options, *, default_value=None):
        recorded.append((title, list(options), default_value))
        return options[0][0]

    monkeypatch.setattr(setup, "_select_from_menu", fake)
    return recorded


@pytest.fixture()
def flow(monkeypatch) -> type[_Flow]:
    _Flow.last_prompt = ""
    _Flow.result = "sk-from-flow"
    _Flow.error = None
    monkeypatch.setattr("questorharness.providers.auth.flows.ApiKeyFlow", _Flow)
    return _Flow


@pytest.fixture()
def install_manager(monkeypatch):
    """Return the manager that every ``AuthManager()`` inside setup_cmd will get."""

    def _install(manager: _Manager) -> _Manager:
        monkeypatch.setattr("questorharness.providers.auth.auth_manager.AuthManager", lambda: manager)
        return manager

    return _install


# --- what the user reads --------------------------------------------------


def test_an_unconfigured_profile_shows_why_it_is_unusable() -> None:
    assert _format_profile_choice_label(STATUSES["claude-api"]) == "Claude API"
    assert _format_profile_choice_label(STATUSES["openai-compatible"]) == "OpenAI (missing auth)"


def test_the_questionary_suffix_carries_a_style_and_none_when_ready() -> None:
    assert _styled_missing_suffix(STATUSES["claude-api"]) is None

    suffix, style = _styled_missing_suffix(STATUSES["custom"])
    assert suffix == " (missing auth)"
    assert style.startswith("fg:")


def test_the_workflow_menu_annotates_each_family(monkeypatch, menu) -> None:
    monkeypatch.setattr(setup, "_can_use_questionary", lambda: False)

    _select_setup_workflow(STATUSES, default_value="openai-compatible")

    title, options, default = menu[0]
    assert title == "Choose a provider workflow:"
    assert default == "openai-compatible"
    assert options[0] == ("claude-api", "Claude API (Claude / Kimi / GLM / MiniMax)")
    assert options[1] == ("openai-compatible", "OpenAI (missing auth) (OpenAI / OpenRouter)")
    # A profile with no family hint still reports that it has no credentials.
    assert options[2] == ("custom", "Custom (missing auth)")


def test_the_questionary_menu_colors_every_hint_and_state_combination(monkeypatch) -> None:
    """All four title shapes, pinned.

    These branches are invisible in a plain terminal, and a refactor that drops one does
    not change any other observable -- so each combination is asserted here by name.
    """
    fake = types.ModuleType("questionary")
    captured: list[dict] = []
    monkeypatch.setitem(sys.modules, "questionary", fake)
    monkeypatch.setattr(setup, "_can_use_questionary", lambda: True)
    monkeypatch.setattr(fake, "Choice", lambda **kwargs: captured.append(kwargs) or kwargs, raising=False)
    monkeypatch.setattr(
        fake,
        "select",
        lambda title, *, choices, default=None: types.SimpleNamespace(ask=lambda: choices[0]["value"]),
        raising=False,
    )
    statuses = {
        "claude-api": STATUSES["claude-api"],
        "openai-compatible": STATUSES["openai-compatible"],
        "custom": STATUSES["custom"],
        "other-ready": {"label": "Other", "configured": True, "auth_state": "ready", "auth_source": "gemini_api_key"},
    }

    assert _select_setup_workflow(statuses, default_value="custom") == "claude-api"

    assert [entry["title"] for entry in captured] == [
        # family hint, nothing missing
        [("", "Claude API  "), ("fg:#7aa2f7", "Claude / Kimi / GLM / MiniMax")],
        # family hint plus the missing-auth warning; strip() removes the padding space
        # but keeps the parentheses
        [
            ("", "OpenAI  "),
            ("fg:#9ece6a", "OpenAI / OpenRouter"),
            ("", "  "),
            ("fg:#d3869b", "(missing auth)"),
        ],
        # no hint to show, so only the warning is colored
        [("", "Custom"), ("fg:#d3869b", " (missing auth)")],
        # nothing to color stays a plain string
        "Other",
    ]
    assert [entry["value"] for entry in captured] == ["claude-api", "openai-compatible", "custom", "other-ready"]
    assert [entry["checked"] for entry in captured] == [False, False, True, False]


def test_aborting_the_questionary_menu_is_a_typer_abort(monkeypatch) -> None:
    fake = types.ModuleType("questionary")
    monkeypatch.setitem(sys.modules, "questionary", fake)
    monkeypatch.setattr(setup, "_can_use_questionary", lambda: True)
    monkeypatch.setattr(fake, "Choice", lambda **kwargs: kwargs, raising=False)
    monkeypatch.setattr(
        fake,
        "select",
        lambda title, *, choices, default=None: types.SimpleNamespace(ask=lambda: None),
        raising=False,
    )

    with pytest.raises(typer.Abort):
        _select_setup_workflow(STATUSES)


# --- key entry ------------------------------------------------------------


def test_a_blank_api_key_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(setup, "_secret_prompt", lambda message: "  sk-live  ")
    assert _prompt_api_key_for_profile("OpenAI") == "sk-live"

    monkeypatch.setattr(setup, "_secret_prompt", lambda message: "   ")
    with pytest.raises(typer.BadParameter, match="cannot be empty"):
        _prompt_api_key_for_profile("OpenAI")


def test_the_key_prompt_names_the_profile_being_configured(monkeypatch, capsys, flow) -> None:
    monkeypatch.setattr(setup, "_login_provider", lambda provider: None)
    manager = _Manager(profiles={"custom": _profile(label="Team gateway")})

    _ensure_profile_auth(manager, "custom")

    assert flow.last_prompt == "Enter API key for Team gateway"
    assert manager.stored == [("custom", "api_key", "sk-from-flow")]
    assert "Team gateway API key saved." in capsys.readouterr().out


def test_a_flow_that_refuses_is_reported_and_exits(monkeypatch, capsys, flow) -> None:
    flow.error = ValueError("no browser available")
    monkeypatch.setattr(setup, "_login_provider", lambda provider: None)
    manager = _Manager(profiles={"custom": _profile(label="Team gateway")})

    with pytest.raises(typer.Exit):
        _ensure_profile_auth(manager, "custom")

    assert manager.stored == []
    assert "Error: no browser available" in capsys.readouterr().err


def test_a_subscription_profile_logs_in_instead_of_asking_for_a_key(monkeypatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(setup, "_login_provider", seen.append)
    manager = _Manager(profiles={"sub": _profile(auth_source="claude_subscription")})

    _ensure_profile_auth(manager, "sub")

    # The subscription is owned by an external CLI, so no key prompt appears.
    assert seen == ["anthropic_claude"]
    assert manager.stored == []


def test_declining_the_key_update_touches_nothing(monkeypatch) -> None:
    monkeypatch.setattr(setup, "_confirm_prompt", lambda message, *, default=False: False)
    asked: list[str] = []
    monkeypatch.setattr(setup, "_ensure_profile_auth", lambda manager, name: asked.append(name))
    manager = _Manager(profiles={"claude-api": _profile(label="Claude API")})

    assert _maybe_update_profile_auth(manager, "claude-api") is False
    assert asked == []


def test_a_profile_without_a_key_is_never_offered_a_key_update(monkeypatch) -> None:
    asked: list[str] = []
    monkeypatch.setattr(setup, "_confirm_prompt", lambda message, *, default=False: asked.append(message) or True)
    manager = _Manager(profiles={"sub": _profile(auth_source="copilot_oauth")})

    assert _maybe_update_profile_auth(manager, "sub") is False
    # The question is not even asked when the auth source holds no key.
    assert asked == []


def test_accepting_the_offer_replaces_the_key(monkeypatch) -> None:
    monkeypatch.setattr(setup, "_confirm_prompt", lambda message, *, default=False: True)
    asked: list[str] = []
    monkeypatch.setattr(setup, "_ensure_profile_auth", lambda manager, name: asked.append(name))
    manager = _Manager(profiles={"claude-api": _profile()})

    assert _maybe_update_profile_auth(manager, "claude-api") is True
    assert asked == ["claude-api"]


# --- custom and preset profiles ------------------------------------------


def test_a_custom_profile_is_built_from_the_answers_and_stores_its_own_key(monkeypatch) -> None:
    answers = iter(["tenant-a", "Tenant A", "https://gateway.internal/v1", "gpt-4o-mini"])
    monkeypatch.setattr(setup, "_select_from_menu", lambda title, options, *, default_value=None: "openai")
    monkeypatch.setattr(setup, "_text_prompt", lambda message, *, default="": next(answers))
    monkeypatch.setattr(setup, "_secret_prompt", lambda message: "sk-tenant")
    manager = _Manager()

    name = _configure_custom_profile_via_setup(manager)

    assert name == "tenant-a"
    created = manager.profiles["tenant-a"]
    assert (created.label, created.provider, created.api_format, created.base_url) == (
        "Tenant A",
        "openai",
        "openai",
        "https://gateway.internal/v1",
    )
    assert created.default_model == "gpt-4o-mini"
    assert created.allowed_models == ["gpt-4o-mini"]
    # A compatible gateway binds its own slot so it never shares the provider key.
    assert created.credential_slot
    assert manager.stored == [("tenant-a", "api_key", "sk-tenant")]


@pytest.mark.parametrize(
    "answers",
    [
        ["", "label", "https://x", "m"],  # no profile name
        ["name", "label", "", "m"],  # no base url
        ["name", "label", "https://x", "   "],  # no default model
    ],
    ids=["no-name", "no-base-url", "no-model"],
)
def test_a_missing_answer_writes_nothing(monkeypatch, answers) -> None:
    index = iter(answers)
    monkeypatch.setattr(setup, "_select_from_menu", lambda title, options, *, default_value=None: "anthropic")
    monkeypatch.setattr(setup, "_text_prompt", lambda message, *, default="": next(index))
    monkeypatch.setattr(setup, "_secret_prompt", lambda message: "sk-1")
    manager = _Manager()

    with pytest.raises(typer.BadParameter):
        _configure_custom_profile_via_setup(manager)

    assert manager.upserts == []
    assert manager.stored == []


def _preset(manager: _Manager, *, lock_model: bool) -> str:
    return _ensure_preset_profile(
        manager,
        name="preset",
        label="Preset",
        provider="anthropic",
        api_format="anthropic",
        auth_source="anthropic_api_key",
        base_url=None,
        model="claude-x",
        lock_model=lock_model,
    )


def test_locking_the_model_replaces_the_allowed_list() -> None:
    manager = _Manager(profiles={"preset": _profile(provider="anthropic", api_format="anthropic", allowed_models=["keep-me"])})

    assert _preset(manager, lock_model=True) == "preset"
    assert manager.profiles["preset"].allowed_models == ["claude-x"]


def test_leaving_the_model_unlocked_keeps_the_list_the_user_had() -> None:
    manager = _Manager(profiles={"preset": _profile(provider="anthropic", api_format="anthropic", allowed_models=["keep-me"])})

    assert _preset(manager, lock_model=False) == "preset"
    assert manager.profiles["preset"].allowed_models == ["keep-me"]


# --- expanding a family choice -------------------------------------------


def test_the_official_option_asks_for_nothing(menu) -> None:
    manager = _Manager()

    assert _specialize_setup_target(manager, "claude-api") == "claude-api"
    assert _specialize_setup_target(manager, "openai-compatible") == "openai-compatible"
    assert [entry[0] for entry in menu] == [
        "Choose an Anthropic-compatible provider:",
        "Choose an OpenAI-compatible provider:",
    ]
    assert manager.upserts == []


def test_a_third_party_anthropic_gateway_is_created_from_the_suggested_defaults(monkeypatch) -> None:
    monkeypatch.setattr(setup, "_select_from_menu", lambda title, options, *, default_value=None: "kimi-anthropic")
    monkeypatch.setattr(setup, "_text_prompt", lambda message, *, default="": default)
    manager = _Manager()

    name = _specialize_setup_target(manager, "claude-api")

    created = manager.profiles[name]
    assert name == "kimi-anthropic"
    assert created.provider == "anthropic"
    assert created.base_url == "https://api.moonshot.cn/anthropic"
    assert (created.default_model, created.allowed_models) == ("kimi-k2.5", ["kimi-k2.5"])


def test_an_empty_base_url_stops_the_gateway_creation(monkeypatch) -> None:
    monkeypatch.setattr(setup, "_select_from_menu", lambda title, options, *, default_value=None: "glm-anthropic")
    answers = iter(["   ", "glm-4.5"])
    monkeypatch.setattr(setup, "_text_prompt", lambda message, *, default="": next(answers))
    manager = _Manager()

    with pytest.raises(typer.BadParameter, match="Base URL"):
        _specialize_setup_target(manager, "claude-api")

    assert manager.upserts == []


def test_openrouter_keeps_the_provider_model_list_open(monkeypatch) -> None:
    monkeypatch.setattr(setup, "_select_from_menu", lambda title, options, *, default_value=None: "openrouter")
    answers = iter(["https://openrouter.ai/api/v1", "any/model"])
    monkeypatch.setattr(setup, "_text_prompt", lambda message, *, default="": next(answers))
    manager = _Manager()

    name = _specialize_setup_target(manager, "openai-compatible")

    created = manager.profiles[name]
    assert name == "openrouter" and created.provider == "openai"
    assert created.allowed_models == []


def test_an_unmatched_target_is_passed_through_unchanged() -> None:
    assert _specialize_setup_target(_Manager(), "already-a-profile") == "already-a-profile"


# --- the command surface --------------------------------------------------


def test_setup_refuses_to_run_without_any_profile(install_manager, capsys) -> None:
    install_manager(_Manager(statuses={}))

    with pytest.raises(typer.Exit) as caught:
        setup_cmd(None)

    assert caught.value.exit_code == 1


def test_setup_names_the_auth_source_the_profile_requires(install_manager, monkeypatch, capsys, flow) -> None:
    """The hint shown before the key prompt is built from the label table."""
    manager = install_manager(
        _Manager(
            statuses={"custom": {"label": "Tenant A", "configured": False, "auth_state": "missing auth", "auth_source": "openai_api_key"}},
            profiles={"custom": _profile(label="Tenant A")},
        )
    )
    monkeypatch.setattr(setup, "_specialize_setup_target", lambda manager_, target: target)
    monkeypatch.setattr(setup, "_prompt_model_for_profile", lambda profile: "gpt-4o")

    setup_cmd("custom")

    printed = capsys.readouterr().out
    assert "Tenant A requires OpenAI API key." in printed
    assert "Setup complete:" in printed and "profile: custom" in printed
    assert manager.activated == ["custom"]
    assert manager.updated == [("custom", {"last_model": "gpt-4o"})]


def test_an_already_configured_profile_is_not_asked_for_a_key_again(
    install_manager, monkeypatch, flow
) -> None:
    manager = install_manager(
        _Manager(
            statuses={"claude-api": {"label": "Claude API", "configured": True, "auth_state": "ready", "auth_source": "anthropic_api_key"}},
            profiles={"claude-api": _profile(label="Claude API", provider="anthropic", api_format="anthropic", auth_source="anthropic_api_key")},
        )
    )
    monkeypatch.setattr(setup, "_specialize_setup_target", lambda manager_, target: target)
    monkeypatch.setattr(setup, "_maybe_update_profile_auth", lambda manager_, name: False)
    monkeypatch.setattr(setup, "_prompt_model_for_profile", lambda profile: "claude-next")

    setup_cmd("claude-api")

    assert flow.last_prompt == ""
    assert manager.stored == []
    assert manager.updated == [("claude-api", {"last_model": "claude-next"})]


def test_the_default_keyword_clears_the_model_override(install_manager, monkeypatch) -> None:
    manager = install_manager(
        _Manager(
            statuses={"claude-api": {"label": "Claude API", "configured": True, "auth_state": "ready", "auth_source": "anthropic_api_key"}},
            profiles={"claude-api": _profile(label="Claude API")},
        )
    )
    monkeypatch.setattr(setup, "_specialize_setup_target", lambda manager_, target: target)
    monkeypatch.setattr(setup, "_maybe_update_profile_auth", lambda manager_, name: False)
    monkeypatch.setattr(setup, "_prompt_model_for_profile", lambda profile: "DEFAULT")

    setup_cmd("claude-api")

    # "default" is a keyword, not a model id: it clears the per-profile override.
    assert manager.updated == [("claude-api", {"last_model": ""})]


def test_a_target_that_vanishes_mid_flow_is_reported(install_manager, monkeypatch, capsys) -> None:
    manager = install_manager(_Manager(statuses={"real": STATUSES["custom"]}))
    monkeypatch.setattr(setup, "_select_setup_workflow", lambda statuses, *, default_value=None: "ghost")

    def _lose_it(manager_, target):
        # The profile list is read again after the target is specialised; a flow that
        # leaves that second read without the target must say so instead of crashing.
        manager_.statuses.clear()
        return target

    monkeypatch.setattr(setup, "_specialize_setup_target", _lose_it)

    with pytest.raises(typer.Exit) as caught:
        setup_cmd(None)

    assert caught.value.exit_code == 1
    assert "Unknown provider profile: 'ghost'" in capsys.readouterr().err
