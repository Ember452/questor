"""Mirror test for ``commands/families/account.py`` (plan 01, R7).

Scope note: ``register_account_commands``/``register_skill_commands``/
``register_config_commands`` were named by no test before this file. This family owns the
remote-invocation flags of ``/login``, ``/logout`` and ``/config`` -- a wrong default here
lets a chat message rewrite credentials -- plus the API-key masking, the feedback log
format and how a skill becomes a slash command. The helpers it borrows
(``_coerce_setting_value``, ``_settings_json_for_display``, ...) already have their own
mirror in ``test_command_display.py``, so this file patches them and pins the routing.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from questorharness.commands.families import account
from questorharness.commands.families.account import (
    register_account_commands,
    register_config_commands,
    register_skill_commands,
)
from questorharness.commands.models import CommandContext, CommandRegistry
from questorharness.config.settings import Settings


def skill(**overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "name": "deploy",
        "command_name": "",
        "display_name": "",
        "description": "Ship it",
        "source": "bundled",
        "path": "",
        "content": "SKILL BODY",
        "base_dir": "",
        "model": None,
        "user_invocable": True,
    }
    return SimpleNamespace(**base | overrides)  # type: ignore[arg-type]


def context() -> CommandContext:
    # every handler in this family either ignores the context or only reads cwd and the
    # skill directories, so no engine is needed
    return CommandContext(engine=object())  # type: ignore[arg-type]


@pytest.fixture()
def registry() -> CommandRegistry:
    return CommandRegistry()


@pytest.fixture()
def settings(monkeypatch):
    """A settings object that never touches disk, with the fields these handlers read."""
    current = SimpleNamespace(
        api_key="sk-1234567890abcdef",
        base_url="",
        model="gpt-4o",
        resolve_profile=lambda: ("work", SimpleNamespace(auth_source="openai_api_key")),
    )
    monkeypatch.setattr(account, "load_settings", lambda: current)
    return current


@pytest.fixture()
def auth(monkeypatch):
    """Record what the handlers ask the credential manager to do."""
    calls: list[tuple] = []

    class _FakeAuthManager:
        def __init__(self, settings) -> None:
            calls.append(("construct", settings))

        def store_profile_credential(self, profile_name, kind, value) -> None:
            calls.append(("store", profile_name, kind, value))

        def clear_profile_credential(self, profile_name) -> None:
            calls.append(("clear", profile_name))

    monkeypatch.setattr(account, "AuthManager", _FakeAuthManager)
    monkeypatch.setattr(account, "detect_provider", lambda _settings: SimpleNamespace(name="openai"))
    monkeypatch.setattr(account, "auth_status", lambda _settings: "ready")
    return calls


@pytest.fixture(autouse=True)
def registered(registry, settings, auth, skills, saved):
    """Every case here runs against the whole family, in the order ``/skills`` expects.

    Registration order matters: the account commands must exist before a skill called
    ``login`` can be refused, which is one of the cases below.
    """
    register_account_commands(registry)
    register_skill_commands(registry)
    register_config_commands(registry)
    return registry


async def handle(registry: CommandRegistry, spoken: str, ctx: CommandContext | None = None):
    found = registry.lookup(spoken)
    assert found is not None, f"{spoken} is not registered"
    command, args = found
    return await command.handler(args, ctx or context())


# --- what may be triggered remotely ---------------------------------------


def test_the_credential_commands_are_not_remotely_invocable(registry, settings, auth) -> None:
    """Pinned: /login and /logout need a terminal, a chat message must not reach them."""
    register_account_commands(registry)

    for name in ("login", "logout"):
        command, _ = registry.lookup(f"/{name}")
        assert command.remote_invocable is False
        assert command.remote_admin_opt_in is True


def test_feedback_and_onboarding_stay_remotely_invocable(registry, settings, auth) -> None:
    register_account_commands(registry)

    for name in ("feedback", "onboarding"):
        command, _ = registry.lookup(f"/{name}")
        assert command.remote_invocable is True
        assert command.remote_admin_opt_in is False


def test_the_config_command_is_local_only(registry, settings) -> None:
    register_config_commands(registry)

    command, _ = registry.lookup("/config")
    assert command.remote_invocable is False
    assert command.remote_admin_opt_in is True


def test_the_family_describes_each_command_as_the_user_sees_it(registry, settings, auth) -> None:
    register_account_commands(registry)
    register_skill_commands(registry)
    register_config_commands(registry)

    described = {command.name: command.description for command in registry.list_commands()}
    assert described["login"] == "Show auth status or store an API key"
    assert described["logout"] == "Clear the stored API key"
    assert described["feedback"] == "Save CLI feedback to the local feedback log"
    assert described["onboarding"] == "Show the quickstart guide"
    assert described["config"] == "Show or update configuration"


# --- /login ---------------------------------------------------------------


async def test_an_empty_login_shows_the_status_with_a_masked_key(registry, settings, auth) -> None:
    result = await handle(registry, "/login")

    assert result.message is not None
    lines = result.message.splitlines()
    assert lines[0] == "Auth status:"
    assert "- profile: work" in lines
    assert "- provider: openai" in lines
    assert "- auth_source: openai_api_key" in lines
    assert "- auth_status: ready" in lines
    assert "- base_url: (default)" in lines
    assert "- model: gpt-4o" in lines
    # six characters in, four out, never the middle
    assert "- api_key: sk-123...cdef" in lines
    assert "sk-1234567890abcdef" not in result.message
    assert lines[-1] == "Usage: /login API_KEY"
    assert [call for call in auth if call[0] == "store"] == []


async def test_an_unconfigured_key_is_reported_as_such(registry, settings, auth) -> None:
    settings.api_key = ""

    message = (await handle(registry, "/login")).message

    assert "- api_key: (not configured)" in message
    assert "None" not in message


async def test_a_pasted_key_is_stored_under_the_active_profile(registry, settings, auth) -> None:
    result = await handle(registry, "/login  sk-new-key  ")

    assert ("store", "work", "api_key", "sk-new-key") in auth
    assert result.message == "Stored API key in ~/.questorharness/settings.json"


async def test_logging_out_clears_only_the_active_profile(registry, settings, auth) -> None:
    result = await handle(registry, "/logout")

    assert ("clear", "work") in auth
    assert result.message == "Cleared stored API key."


# --- /feedback ------------------------------------------------------------


async def test_the_usage_line_does_not_create_a_log(registry, settings, auth, monkeypatch, tmp_path) -> None:
    log = tmp_path / "feedback.log"
    monkeypatch.setattr(account, "get_feedback_log_path", lambda: log)

    message = (await handle(registry, "/feedback")).message

    assert message == f"Feedback log: {log}\nUsage: /feedback TEXT"
    assert not log.exists()


async def test_feedback_appends_one_timestamped_line_per_call(registry, settings, auth, monkeypatch, tmp_path) -> None:
    log = tmp_path / "feedback.log"
    monkeypatch.setattr(account, "get_feedback_log_path", lambda: log)

    first = await handle(registry, "/feedback  model ignored my tool  ")
    second = await handle(registry, "/feedback second note")

    assert first.message == f"Saved feedback to {log}"
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("[")
    assert lines[0].endswith("] model ignored my tool")
    # the bracket really is an ISO-8601 UTC timestamp, not a free-form note
    datetime.fromisoformat(lines[0][1 : lines[0].index("]")])
    assert lines[1].endswith("] second note")


async def test_onboarding_lists_the_quickstart_steps(registry, settings, auth) -> None:
    message = (await handle(registry, "/onboarding")).message

    assert message.startswith("QuestorHarness quickstart:")
    assert "2. Use /help to inspect commands." in message
    assert "5. Use /login to store an API key if needed." in message


# --- /config --------------------------------------------------------------


@pytest.fixture()
def saved(monkeypatch):
    calls: list[object] = []
    monkeypatch.setattr(account, "save_settings", lambda settings: calls.append(settings))
    monkeypatch.setattr(account, "_settings_json_for_display", lambda settings: '{"model": "shown"}')
    return calls


def a_string_field() -> str:
    for name, info in Settings.model_fields.items():
        if info.annotation is str:
            return name
    raise AssertionError("Settings has no plain str field to drive /config set")


async def test_config_shows_the_display_json_for_both_spellings(registry, settings, saved) -> None:
    assert (await handle(registry, "/config")).message == '{"model": "shown"}'
    assert (await handle(registry, "/config show")).message == '{"model": "shown"}'


async def test_an_unknown_key_is_refused_without_saving(registry, settings, saved) -> None:
    result = await handle(registry, "/config set not_a_setting value")

    assert result.message == "Unknown config key: not_a_setting"
    assert saved == []


async def test_a_value_keeps_its_spaces(registry, settings, saved, monkeypatch) -> None:
    """``split(maxsplit=2)`` is what lets a value contain whitespace."""
    key = a_string_field()
    monkeypatch.setattr(account, "_coerce_setting_value", lambda settings, key, value: value.upper())

    result = await handle(registry, f"/config set {key} alpha beta gamma")

    assert result.message == f"Updated {key}"
    assert getattr(settings, key) == "ALPHA BETA GAMMA"
    assert saved == [settings]


async def test_a_rejected_value_is_surfaced_verbatim(registry, settings, saved, monkeypatch) -> None:
    key = a_string_field()

    def refuse(_settings, _key, _value):
        raise ValueError("model must not be empty")

    monkeypatch.setattr(account, "_coerce_setting_value", refuse)

    assert (await handle(registry, f"/config set {key} x")).message == "model must not be empty"
    assert saved == []


async def test_a_half_written_command_shows_the_usage(registry, settings, saved) -> None:
    assert (await handle(registry, "/config set only_key")).message == "Usage: /config [show|set KEY VALUE]"
    assert (await handle(registry, "/config toggle on")).message == "Usage: /config [show|set KEY VALUE]"


# --- /skills --------------------------------------------------------------


@pytest.fixture()
def skills(monkeypatch):
    """A skill registry plus a record of how each call site asks for one.

    Both the family module and the shared display helper load a registry, so both
    attributes are pointed at the same fake: the auto-generated ``/skill`` commands run
    through ``command_display``.
    """
    calls: list[tuple] = []
    state: dict[str, list] = {"listed": []}

    class _FakeSkillRegistry:
        def list_skills(self):
            return list(state["listed"])

        def get(self, name):
            return next((item for item in state["listed"] if (item.command_name or item.name) == name), None)

    def load(*args, **kwargs):
        calls.append((args, kwargs))
        return _FakeSkillRegistry()

    from questorharness.commands import command_display

    monkeypatch.setattr(account, "load_skill_registry", load)
    monkeypatch.setattr(command_display, "load_skill_registry", load)
    return SimpleNamespace(calls=calls, state=state)


async def test_listing_a_skill_shows_source_path_and_the_slash_alias(registry, settings, auth, skills) -> None:
    skills.state["listed"] = [
        skill(command_name="deploy", display_name="Deploy", source="project", path="skills/deploy", description="Ship it"),
        skill(name="My Skill", command_name="", user_invocable=True, source="bundled"),
        skill(name="quiet", user_invocable=False, source="plugin"),
    ]
    register_skill_commands(registry)

    message = (await handle(registry, "/skills")).message
    lines = message.splitlines()

    assert lines[0] == "Available skills:"
    assert lines[1] == "- deploy (Deploy) [project] skills/deploy /deploy: Ship it"
    # a name with a space cannot become a slash command, so no alias is advertised
    assert lines[2] == "- My Skill [bundled]: Ship it"
    assert lines[3] == "- quiet [plugin]: Ship it"
    assert "/quiet" not in message


async def test_an_empty_skill_directory_is_not_an_error(registry, settings, auth, skills) -> None:
    register_skill_commands(registry)

    assert (await handle(registry, "/skills")).message == "No skills available."


async def test_asking_for_one_skill_returns_its_body(registry, settings, auth, skills) -> None:
    skills.state["listed"] = [skill(command_name="deploy")]
    register_skill_commands(registry)

    assert (await handle(registry, "/skills deploy")).message == "SKILL BODY"
    assert (await handle(registry, "/skills ghost")).message == "Skill not found: ghost"


async def test_the_handler_rescans_for_the_current_context(registry, settings, auth, skills) -> None:
    """Registration loads a registry with no arguments; running one uses the context."""
    register_skill_commands(registry)

    assert skills.calls[0] == ((), {})

    ctx = CommandContext(engine=object(), cwd=r"D:\proj", extra_skill_dirs=["extra"], extra_plugin_roots=["roots"])
    skills.calls.clear()
    await handle(registry, "/skills", ctx)

    assert skills.calls[0] == ((r"D:\proj",), {"extra_skill_dirs": ["extra"], "extra_plugin_roots": ["roots"]})


async def test_user_invocable_skills_become_their_own_commands(registry, settings, auth, skills) -> None:
    skills.state["listed"] = [skill(command_name="deploy"), skill(name="nope", user_invocable=False)]
    register_skill_commands(registry)

    command, _ = registry.lookup("/deploy")
    assert command.description == "Invoke the deploy skill"
    assert registry.lookup("/nope") is None

    result = await command.handler("", context())

    # pinned: a skill command does not print the skill, it submits it as a prompt
    assert result.message is None
    assert result.submit_prompt == "SKILL BODY"
    assert result.submit_model is None


def test_a_skill_never_shadows_a_real_command(registry, settings, auth, skills) -> None:
    """Pinned: a skill named ``login`` is not registered over ``/login``."""
    register_account_commands(registry)
    skills.state["listed"] = [skill(command_name="login")]
    register_skill_commands(registry)

    command, _ = registry.lookup("/login")
    assert command.description == "Show auth status or store an API key"


async def test_the_skill_body_of_a_shadowed_command_is_still_readable(registry, settings, auth, skills) -> None:
    """``/skills login`` goes through the lookup, so the skill body is reachable."""
    register_account_commands(registry)
    skills.state["listed"] = [skill(command_name="login")]
    register_skill_commands(registry)

    assert (await handle(registry, "/skills login")).message == "SKILL BODY"
