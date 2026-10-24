"""Mirror test for ``commands/command_display.py`` (plan 01, R7).

Scope note: the slash-command *flows* are covered by ``test_command_flows.py`` and the
registry by ``test_registry.py``. The two helpers that decide what leaves the machine —
secret redaction and prompt templating — had no test at all, which is the reason this
module was renamed away from the generic ``helpers`` bucket in the first place.
"""

from __future__ import annotations

import json

import pytest

from questorharness.capabilities.skills.definition import SkillDefinition
from questorharness.commands.command_display import (
    _REDACTED,
    _coerce_setting_value,
    _is_secret_key,
    _is_valid_skill_command_name,
    _redact_config_value,
    _render_plugin_command_prompt,
    _render_skill_command_prompt,
    _settings_json_for_display,
    _skill_command_name,
)
from questorharness.config.settings import Settings
from questorharness.plugins.models import PluginCommandDefinition


def _skill(content: str, **overrides) -> SkillDefinition:
    kwargs = {"name": "review", "description": "Review a diff", "content": content, "source": "project"}
    kwargs.update(overrides)
    return SkillDefinition(**kwargs)


def _plugin(content: str, **overrides) -> PluginCommandDefinition:
    kwargs = {"name": "changelog", "description": "Summarise commits", "content": content}
    kwargs.update(overrides)
    return PluginCommandDefinition(**kwargs)


@pytest.mark.parametrize(
    "key",
    ["api_key", "API-KEY", "OPENAI_APIKEY", "auth_token", "access_token", "refresh_token", "client-secret"],
)
def test_secret_key_names_are_recognised(key: str) -> None:
    assert _is_secret_key(key) is True


@pytest.mark.parametrize("key", ["model", "theme", "verbose", "base_url", None, 7])
def test_ordinary_keys_are_not_secret(key: object) -> None:
    assert _is_secret_key(key) is False


def test_the_matcher_is_substring_based_and_errs_towards_redaction() -> None:
    # ``max_tokens`` is a plain int setting, yet it carries the substring "token", so it
    # is treated as secret. That is deliberate: the display path would rather hide a
    # harmless number than miss a token field spelled an unexpected way.
    assert _is_secret_key("max_tokens") is True
    assert _is_secret_key("context_window_tokens") is True


def test_a_secret_key_short_circuits_its_value() -> None:
    assert _redact_config_value("sk-live", key="api_key") == _REDACTED


def test_nested_containers_are_redacted_by_key() -> None:
    value = {
        "model": "claude",
        "credentials": {"api_key": "sk-live", "token": "t0ken"},
        "auth": {"nested": {"api_key": "sk-deep"}},
        "allowed": ["ok", {"secret": "hidden"}],
        "shapes": ["Bearer abc.def", "plain"],
        "pairs": (("public", "visible"), ("password", "p@ss")),
    }

    redacted = _redact_config_value(value)

    assert redacted["model"] == "claude"
    # A key that is itself secret collapses the whole subtree, not just its leaves.
    assert redacted["credentials"] == _REDACTED
    # "auth" alone is not on the secret list, so this subtree is walked and only the
    # leaf that carries a secret name is replaced.
    assert redacted["auth"] == {"nested": {"api_key": _REDACTED}}
    assert redacted["allowed"] == ["ok", {"secret": _REDACTED}]
    # Sequence elements carry no key, so only the value shape can trigger redaction.
    assert redacted["shapes"] == [_REDACTED, "plain"]
    # Tuples degrade to lists because the display form is JSON, and JSON has no tuples.
    # Their elements are visited without a key, so a literal like "password" survives as
    # data: the secret here would have to look like a credential header to be caught.
    assert redacted["pairs"] == [["public", "visible"], ["password", "p@ss"]]


def test_authorization_style_strings_are_redacted_by_shape() -> None:
    assert _redact_config_value("Bearer abc.def") == _REDACTED
    assert _redact_config_value("basic Zm9vOmJhcg==") == _REDACTED
    assert _redact_config_value("https://example.com/api") == "https://example.com/api"


def test_settings_json_never_leaks_the_api_key() -> None:
    dumped = _settings_json_for_display(Settings(api_key="sk-should-not-appear"))

    assert "sk-should-not-appear" not in dumped
    assert _REDACTED in dumped
    assert json.loads(dumped)["api_key"] == _REDACTED


def test_coercion_follows_the_declared_field_type() -> None:
    settings = Settings()

    assert _coerce_setting_value(settings, "verbose", "yes") is True
    assert _coerce_setting_value(settings, "verbose", "ON") is True
    assert _coerce_setting_value(settings, "verbose", "0") is False
    assert _coerce_setting_value(settings, "max_tokens", "8192") == 8192
    assert _coerce_setting_value(settings, "theme", "dark") == "dark"


def test_coercion_rejects_an_unparsable_bool_or_unknown_key() -> None:
    settings = Settings()

    with pytest.raises(ValueError):
        _coerce_setting_value(settings, "verbose", "perhaps")
    with pytest.raises(ValueError):
        _coerce_setting_value(settings, "max_tokens", "many")
    with pytest.raises(KeyError):
        _coerce_setting_value(settings, "not_a_field", "x")


def test_plugin_prompt_substitutes_both_argument_spellings() -> None:
    assert _render_plugin_command_prompt(_plugin("Diff: ${ARGUMENTS}"), "HEAD~3", None) == "Diff: HEAD~3"
    assert _render_plugin_command_prompt(_plugin("Diff: $ARGUMENTS"), "HEAD~3", None) == "Diff: HEAD~3"
    assert _render_plugin_command_prompt(_plugin("No placeholder"), "", None) == "No placeholder"


def test_plugin_prompt_appends_arguments_when_the_template_ignores_them() -> None:
    rendered = _render_plugin_command_prompt(_plugin("Summarise the release."), " v1.2 ", None)

    assert rendered == "Summarise the release.\n\nArguments: v1.2"


def test_plugin_prompt_substitutes_the_session_id() -> None:
    rendered = _render_plugin_command_prompt(_plugin("session=${CLAUDE_SESSION_ID}"), "", "sess-9")

    assert rendered == "session=sess-9"


def test_skill_typed_plugin_command_gets_a_base_directory_header() -> None:
    rendered = _render_plugin_command_prompt(
        _plugin("Read ${CLAUDE_SKILL_DIR}/notes.md", is_skill=True, base_dir="/skills/release"),
        "",
        None,
    )

    assert rendered.startswith("Base directory for this skill: /skills/release\n\n")
    assert "/skills/release/notes.md" in rendered


def test_skill_prompt_templating_matches_the_plugin_variant() -> None:
    assert _render_skill_command_prompt(_skill("Run $ARGUMENTS"), "now", None) == "Run now"

    appended = _render_skill_command_prompt(_skill("Run it"), "now", None)
    assert appended == "Run it\n\nArguments: now"

    with_dir = _render_skill_command_prompt(_skill("At ${CLAUDE_SKILL_DIR}", base_dir="/skills/x"), "", "s-1")
    assert with_dir.startswith("Base directory for this skill: /skills/x\n\n")
    assert "At /skills/x" in with_dir

    with_session = _render_skill_command_prompt(_skill("id=${CLAUDE_SESSION_ID}"), "", "s-7")
    assert with_session == "id=s-7"


def test_command_name_prefers_the_declared_alias() -> None:
    assert _skill_command_name(_skill("x", name="internal", command_name="release")) == "release"
    assert _skill_command_name(_skill("x", name="internal")) == "internal"


@pytest.mark.parametrize("name", ["release", "review-pr", "a1"])
def test_valid_command_names(name: str) -> None:
    assert _is_valid_skill_command_name(name) is True


@pytest.mark.parametrize("name", ["", "has space", "tab\there", "trailing "])
def test_invalid_command_names(name: str) -> None:
    assert _is_valid_skill_command_name(name) is False
