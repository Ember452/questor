"""Mirror test for ``bootstrap/cli/auth_commands.py`` (plan 01, R7).

Scope note: the auth group and the provider binding it drives moved here together,
because the setup wizard calls the same two helpers. Nothing tested this module's own
decisions before: which provider a menu number maps to, what happens to an answer that
is neither a number nor a known provider, and the routing between the device flow, the
external-CLI binding and a plain API key. The three places a provider label is printed
are asserted here on purpose -- row 103 recorded that no test observed them.
"""

from __future__ import annotations

import dataclasses

import pytest
import typer
from typer.testing import CliRunner

from questorharness.bootstrap.cli import auth_commands
from questorharness.bootstrap.cli.auth_commands import (
    _PROVIDER_LABELS,
    _bind_external_provider,
    _login_provider,
    auth_app,
    auth_status_cmd,
)

runner = CliRunner()


class _Manager:
    def __init__(self, *, active="claude-api", sources=None, profiles=None):
        self.active = active
        self.sources = sources or {}
        self.profiles = profiles or {}
        self.switched: list[str] = []
        self.stored: list[tuple[str, str, str]] = []
        self.cleared_providers: list[str] = []
        self.cleared_profiles: list[str] = []
        self.error: Exception | None = None

    def get_active_profile(self):
        return self.active

    def get_auth_source_statuses(self):
        return self.sources

    def get_profile_statuses(self):
        return self.profiles

    def switch_provider(self, name):
        if self.error is not None:
            raise self.error
        self.switched.append(name)

    def store_credential(self, provider, key, value):
        self.stored.append((provider, key, value))

    def clear_credential(self, provider):
        self.cleared_providers.append(provider)

    def clear_profile_credential(self, name):
        self.cleared_profiles.append(name)


@pytest.fixture()
def manager(monkeypatch):
    holder: dict[str, _Manager] = {}

    def _install(instance: _Manager) -> _Manager:
        holder["instance"] = instance
        monkeypatch.setattr("questorharness.providers.auth.auth_manager.AuthManager", lambda: instance)
        return instance

    def _current() -> _Manager:
        return holder["instance"]

    _install.current = _current  # type: ignore[attr-defined]
    return _install


@pytest.fixture(autouse=True)
def _reset_flow() -> None:
    """The fake flow is class-level, so one test's injected error must not leak."""
    _Flow.last_prompt = ""
    _Flow.result = "sk-flow"
    _Flow.error = None


@pytest.fixture()
def routes(monkeypatch):
    """Record which of the three login routes a provider takes."""
    seen: dict[str, list[str]] = {"copilot": [], "bind": [], "login": []}

    monkeypatch.setattr(auth_commands, "_run_copilot_login", lambda: seen["copilot"].append("copilot"))
    monkeypatch.setattr(auth_commands, "_bind_external_provider", lambda provider: seen["bind"].append(provider))
    monkeypatch.setattr(auth_commands, "_login_provider", lambda provider: seen["login"].append(provider))
    return seen


class _Flow:
    last_prompt = ""
    result = "sk-flow"
    error: Exception | None = None

    def __init__(self, *, provider: str, prompt_text: str) -> None:
        type(self).last_prompt = prompt_text
        self.provider = provider

    def run(self) -> str:
        if type(self).error is not None:
            raise type(self).error
        return type(self).result


@dataclasses.dataclass
class _Binding:
    provider: str
    source_path: str
    source_kind: str
    managed_by: str
    profile_label: str


# --- the login menu -------------------------------------------------------


def test_a_menu_number_selects_that_provider(monkeypatch, routes) -> None:
    monkeypatch.setattr(typer, "prompt", lambda message, *, default="": "2")

    result = runner.invoke(auth_app, ["login"])

    assert result.exit_code == 0
    # Position 2 of the label table is the Claude subscription, not the plain API key.
    assert routes["login"] == ["anthropic_claude"]
    assert "Select a provider to authenticate:" in result.output
    assert f"2. {_PROVIDER_LABELS['anthropic_claude']} [anthropic_claude]" in result.output


def test_the_login_menu_lists_every_entry_in_the_label_table(monkeypatch, routes) -> None:
    """The menu and the table cannot drift: each provider must appear as "label [name]".

    Row 103 recorded that changing a label was invisible to the suite because only two
    entries happened to be asserted. This pins the relationship instead of the strings.
    """
    monkeypatch.setattr(typer, "prompt", lambda message, *, default="": "1")

    result = runner.invoke(auth_app, ["login"])

    assert result.exit_code == 0
    for name, label in _PROVIDER_LABELS.items():
        assert f"{label} [{name}]" in result.output


def test_an_out_of_range_number_is_refused_instead_of_guessing(monkeypatch, routes) -> None:
    monkeypatch.setattr(typer, "prompt", lambda message, *, default="": "99")

    result = runner.invoke(auth_app, ["login"])

    assert result.exit_code == 1
    assert routes["login"] == []
    assert "Invalid selection." in result.output


def test_a_name_answer_is_used_as_the_provider(monkeypatch, routes) -> None:
    monkeypatch.setattr(typer, "prompt", lambda message, *, default="": "  Copilot ")

    runner.invoke(auth_app, ["login"])

    assert routes["login"] == ["copilot"]


def test_an_explicit_provider_argument_is_lower_cased(routes) -> None:
    result = runner.invoke(auth_app, ["login", "OpenAI"])

    assert result.exit_code == 0
    assert routes["login"] == ["openai"]


# --- routing inside the login kernel -------------------------------------


def test_copilot_takes_the_device_flow_not_an_api_key(monkeypatch, routes) -> None:
    _login_provider("copilot")

    assert routes["copilot"] == ["copilot"]
    assert routes["bind"] == []


@pytest.mark.parametrize("provider", ["openai_codex", "anthropic_claude"])
def test_subscription_providers_are_bound_from_their_cli(monkeypatch, routes, provider) -> None:
    _login_provider(provider)

    assert routes["bind"] == [provider]
    assert routes["copilot"] == []


def test_an_unknown_provider_is_reported_with_the_list_it_can_choose(monkeypatch, capsys) -> None:
    with pytest.raises(typer.Exit):
        _login_provider("telepathy")

    err = capsys.readouterr().err
    assert "Unknown provider: 'telepathy'" in err
    # The suggestion comes from the same table the menu renders, so the two cannot drift.
    for name in _PROVIDER_LABELS:
        assert name in err


def test_an_api_key_provider_saves_the_key_and_shows_its_label(monkeypatch, capsys, manager, routes) -> None:
    installed = manager(_Manager())
    monkeypatch.setattr("questorharness.providers.auth.flows.ApiKeyFlow", _Flow)
    stored: list[tuple[str, str, str]] = []
    monkeypatch.setattr("questorharness.providers.auth.storage.store_credential", lambda *args: stored.append(args))

    _login_provider("openai")

    assert _Flow.last_prompt == "Enter your OpenAI / compatible API key"
    assert stored == [("openai", "api_key", "sk-flow")]
    assert installed.stored == [("openai", "api_key", "sk-flow")]
    assert "OpenAI / compatible API key saved." in capsys.readouterr().out


def test_a_refused_api_key_is_reported_and_exits(monkeypatch, capsys, manager) -> None:
    installed = manager(_Manager())
    _Flow.error = ValueError("clipboard unavailable")
    monkeypatch.setattr("questorharness.providers.auth.flows.ApiKeyFlow", _Flow)

    with pytest.raises(typer.Exit):
        _login_provider("openai")

    assert "Error: clipboard unavailable" in capsys.readouterr().err
    assert installed.stored == []

def test_a_profile_that_cannot_store_the_key_still_keeps_the_credential_store(monkeypatch, capsys, manager) -> None:
    """The manager mirror is best effort; the credential store is the source of truth."""

    class _Broken(_Manager):
        def store_credential(self, provider, key, value):
            raise RuntimeError("settings file is locked")

    installed = manager(_Broken())
    monkeypatch.setattr("questorharness.providers.auth.flows.ApiKeyFlow", _Flow)
    stored: list[tuple[str, str, str]] = []
    monkeypatch.setattr("questorharness.providers.auth.storage.store_credential", lambda *args: stored.append(args))

    _login_provider("openai")

    assert stored == [("openai", "api_key", "sk-flow")]
    assert "OpenAI / compatible API key saved." in capsys.readouterr().out


def test_binding_a_subscription_reports_where_it_came_from(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "questorharness.providers.auth.external.default_binding_for_provider",
        lambda provider: _Binding(provider, "", "cli", "claude", ""),
    )
    credential = _Binding("anthropic_claude", "/home/u/.claude/.credentials.json", "file", "claude-cli", "work")
    monkeypatch.setattr("questorharness.providers.auth.external.load_external_credential", lambda binding, *, refresh_if_needed: credential)
    saved: list[_Binding] = []
    monkeypatch.setattr("questorharness.providers.auth.storage.store_external_binding", saved.append)
    refreshed: list[str] = []
    monkeypatch.setattr(auth_commands, "_maybe_update_default_model_for_provider", refreshed.append)

    _bind_external_provider("anthropic_claude")

    out = capsys.readouterr().out
    assert f"{_PROVIDER_LABELS['anthropic_claude']} bound from {credential.source_path}." in out
    assert "Use `oh provider use claude-subscription` to activate it." in out
    assert refreshed == ["anthropic_claude"]
    # What gets persisted is the *default* binding's coordinates with the discovered
    # profile label grafted on -- not the credential's own path. Asserted as-is; whether
    # the stored record should carry the real source path is a question for the auth刀
    # (recorded in the ledger, not changed here).
    assert saved == [_Binding(provider="anthropic_claude", source_path="", source_kind="cli", managed_by="claude", profile_label="work")]


def test_a_binding_that_is_missing_on_disk_exits(monkeypatch, capsys) -> None:
    monkeypatch.setattr("questorharness.providers.auth.external.default_binding_for_provider", lambda provider: _Binding(provider, "", "cli", "codex", ""))

    def _missing(binding, *, refresh_if_needed):
        raise ValueError("no codex credentials found")

    monkeypatch.setattr("questorharness.providers.auth.external.load_external_credential", _missing)
    saved: list[object] = []
    monkeypatch.setattr("questorharness.providers.auth.storage.store_external_binding", saved.append)

    with pytest.raises(typer.Exit):
        _bind_external_provider("openai_codex")

    assert "Error: no codex credentials found" in capsys.readouterr().err
    assert saved == []


# --- status, switch, logout ----------------------------------------------


def test_status_prints_labels_and_marks_what_is_active(monkeypatch, capsys, manager) -> None:
    manager(
        _Manager(
            sources={
                "anthropic_api_key": {"state": "configured", "source": "env", "active": True, "detail": "OPENAI_API_KEY"},
                "copilot_oauth": {"state": "missing", "source": "none", "active": False},
            },
            profiles={
                "claude-api": {"label": "Claude API", "provider": "anthropic", "auth_source": "anthropic_api_key", "configured": True, "active": True},
                "kimi": {"label": "Kimi", "provider": "anthropic", "auth_source": "moonshot_api_key", "configured": False, "auth_state": "missing auth", "active": False},
            },
        )
    )

    auth_status_cmd()

    out = capsys.readouterr().out
    assert "Anthropic API key" in out
    assert "<-- active" in out
    assert "detail: OPENAI_API_KEY" in out
    # An unconfigured profile row shows its state instead of a bare "ready".
    assert "missing auth" in out


def test_switch_reports_an_unknown_name(manager) -> None:
    installed = manager(_Manager())
    installed.error = ValueError("Unknown provider or auth source: 'nope'")

    result = runner.invoke(auth_app, ["switch", "nope"])

    assert result.exit_code == 1
    assert "Error: Unknown provider or auth source" in result.output
    assert installed.switched == []


def test_switch_accepts_a_profile_by_name(manager) -> None:
    installed = manager(_Manager())

    result = runner.invoke(auth_app, ["switch", "codex"])

    assert result.exit_code == 0
    assert installed.switched == ["codex"]
    assert "Switched auth/profile to: codex" in result.output


def test_logout_without_an_argument_clears_the_active_profile(manager) -> None:
    installed = manager(_Manager(active="claude-api"))

    result = runner.invoke(auth_app, ["logout"])

    assert result.exit_code == 0
    assert installed.cleared_profiles == ["claude-api"]
    assert installed.cleared_providers == []
    assert "Authentication cleared for profile: claude-api" in result.output


def test_logout_with_a_provider_clears_that_provider(manager) -> None:
    installed = manager(_Manager())

    result = runner.invoke(auth_app, ["logout", "openai"])

    assert result.exit_code == 0
    assert installed.cleared_providers == ["openai"]
    assert installed.cleared_profiles == []
    assert "Authentication cleared for provider: openai" in result.output
