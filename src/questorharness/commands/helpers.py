"""Secret redaction, settings rendering and skill prompt helpers."""

from __future__ import annotations

import json
from typing import Literal, get_args

from questorharness.capabilities.skills import load_skill_registry
from questorharness.capabilities.skills.definition import SkillDefinition
from questorharness.config.settings import Settings
from questorharness.plugins.models import PluginCommandDefinition

from questorharness.commands.types import CommandContext, CommandResult, SlashCommand


_SECRET_KEY_PARTS = (
    "api_key",
    "apikey",
    "auth_token",
    "access_token",
    "refresh_token",
    "token",
    "secret",
    "password",
    "authorization",
    "credential",
    "private_key",
)

_REDACTED = "[REDACTED]"


def _is_secret_key(key: object) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return any(part in normalized for part in _SECRET_KEY_PARTS)


def _redact_config_value(value: object, *, key: object | None = None) -> object:
    if key is not None and _is_secret_key(key):
        return _REDACTED
    if isinstance(value, dict):
        return {item_key: _redact_config_value(item_value, key=item_key) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_redact_config_value(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_config_value(item) for item in value]
    if isinstance(value, str) and value.lower().startswith(("bearer ", "basic ")):
        return _REDACTED
    return value


def _settings_json_for_display(settings: Settings) -> str:
    return json.dumps(_redact_config_value(settings.model_dump()), indent=2, default=str)


def _coerce_setting_value(settings: Settings, key: str, raw: str):
    field = Settings.model_fields.get(key)
    if field is None:
        raise KeyError(key)
    annotation = field.annotation
    if annotation is bool:
        lowered = raw.lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"Invalid boolean value for {key}: {raw}")
    if annotation is int:
        return int(raw)
    if annotation is str:
        return raw
    if annotation is Literal or getattr(annotation, "__origin__", None) is Literal:
        allowed = get_args(annotation)
        if raw not in allowed:
            raise ValueError(f"Invalid value for {key}: {raw}")
        return raw
    return raw


def _render_plugin_command_prompt(command: PluginCommandDefinition, args: str, session_id: str | None = None) -> str:
    prompt = command.content
    raw_args = args.strip()
    if command.is_skill and command.base_dir:
        prompt = f"Base directory for this skill: {command.base_dir}\n\n{prompt}"
        prompt = prompt.replace("${CLAUDE_SKILL_DIR}", command.base_dir)
    prompt = prompt.replace("${ARGUMENTS}", raw_args).replace("$ARGUMENTS", raw_args)
    if session_id:
        prompt = prompt.replace("${CLAUDE_SESSION_ID}", session_id)
    if raw_args and "${ARGUMENTS}" not in command.content and "$ARGUMENTS" not in command.content:
        prompt = f"{prompt}\n\nArguments: {raw_args}"
    return prompt


def _render_skill_command_prompt(skill: SkillDefinition, args: str, session_id: str | None = None) -> str:
    prompt = skill.content
    raw_args = args.strip()
    if skill.base_dir:
        prompt = f"Base directory for this skill: {skill.base_dir}\n\n{prompt}"
        prompt = prompt.replace("${CLAUDE_SKILL_DIR}", skill.base_dir)
    prompt = prompt.replace("${ARGUMENTS}", raw_args).replace("$ARGUMENTS", raw_args)
    if session_id:
        prompt = prompt.replace("${CLAUDE_SESSION_ID}", session_id)
    if raw_args and "${ARGUMENTS}" not in skill.content and "$ARGUMENTS" not in skill.content:
        prompt = f"{prompt}\n\nArguments: {raw_args}"
    return prompt


def _skill_command_name(skill: SkillDefinition) -> str:
    return skill.command_name or skill.name


def _is_valid_skill_command_name(name: str) -> bool:
    return bool(name) and not any(char.isspace() for char in name)


async def _skill_command_handler(args: str, context: CommandContext, *, skill_name: str) -> CommandResult:
    skill_registry = load_skill_registry(
        context.cwd,
        extra_skill_dirs=context.extra_skill_dirs,
        extra_plugin_roots=context.extra_plugin_roots,
    )
    skill = skill_registry.get(skill_name)
    if skill is None:
        return CommandResult(message=f"Skill not found: {skill_name}", refresh_runtime=True)
    if not skill.user_invocable:
        return CommandResult(
            message=(
                f"This skill can only be invoked by the model, not directly by users. "
                f"Ask the model to use the {skill_name!r} skill for you."
            )
        )
    prompt = _render_skill_command_prompt(skill, args, getattr(context, "session_id", None))
    return CommandResult(submit_prompt=prompt, submit_model=skill.model)


def _make_skill_slash_command(skill_name: str, description: str) -> SlashCommand:
    return SlashCommand(
        skill_name,
        description,
        lambda args, context, skill_name=skill_name: _skill_command_handler(
            args,
            context,
            skill_name=skill_name,
        ),
    )

# questor: allow R3 -- until W9 rename wave
