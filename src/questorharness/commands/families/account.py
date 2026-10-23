"""Register account, feedback and onboarding commands. Register user-invocable skill commands. Register the /config command."""

from __future__ import annotations

from datetime import datetime, timezone
from questorharness.capabilities.skills import load_skill_registry
from questorharness.commands.helpers import _coerce_setting_value, _is_valid_skill_command_name, _make_skill_slash_command, _settings_json_for_display, _skill_command_name
from questorharness.config.settings import Settings, load_settings, save_settings
from questorharness.platform.paths import get_feedback_log_path
from questorharness.providers.auth.manager import AuthManager
from questorharness.providers.llm.provider import auth_status, detect_provider

from questorharness.commands.types import (
    CommandContext,
    CommandRegistry,
    CommandResult,
    SlashCommand,
)


def _register_user_invocable_skill_commands(registry: CommandRegistry) -> None:
    """Register loaded skills as slash commands.

    Skills are loaded at command execution time because the active command
    context supplies cwd, questor extra skill dirs, and plugin roots.
    """

    for skill in load_skill_registry().list_skills():
        if not skill.user_invocable:
            continue
        command_name = _skill_command_name(skill)
        if not _is_valid_skill_command_name(command_name):
            continue
        if registry.lookup(f"/{command_name}") is not None:
            continue
        registry.register(
            _make_skill_slash_command(command_name, f"Invoke the {command_name} skill")
        )


def register_account_commands(registry: CommandRegistry) -> None:
    """Register account, feedback and onboarding commands."""

    async def _login_handler(args: str, context: CommandContext) -> CommandResult:
        del context
        settings = load_settings()
        manager = AuthManager(settings)
        profile_name, profile = settings.resolve_profile()
        provider = detect_provider(settings)
        api_key = args.strip()
        if not api_key:
            masked = (
                f"{settings.api_key[:6]}...{settings.api_key[-4:]}"
                if settings.api_key
                else "(not configured)"
            )
            return CommandResult(
                message=(
                    f"Auth status:\n"
                    f"- profile: {profile_name}\n"
                    f"- provider: {provider.name}\n"
                    f"- auth_source: {profile.auth_source}\n"
                    f"- auth_status: {auth_status(settings)}\n"
                    f"- base_url: {settings.base_url or '(default)'}\n"
                    f"- model: {settings.model}\n"
                    f"- api_key: {masked}\n"
                    "Usage: /login API_KEY"
                )
            )
        manager.store_profile_credential(profile_name, "api_key", api_key)
        return CommandResult(message="Stored API key in ~/.questorharness/settings.json")

    async def _logout_handler(_: str, context: CommandContext) -> CommandResult:
        del context
        settings = load_settings()
        profile_name = settings.resolve_profile()[0]
        AuthManager(settings).clear_profile_credential(profile_name)
        return CommandResult(message="Cleared stored API key.")

    async def _feedback_handler(args: str, context: CommandContext) -> CommandResult:
        del context
        path = get_feedback_log_path()
        if not args.strip():
            return CommandResult(message=f"Feedback log: {path}\nUsage: /feedback TEXT")
        timestamp = datetime.now(timezone.utc).isoformat()
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {args.strip()}\n")
        return CommandResult(message=f"Saved feedback to {path}")

    async def _onboarding_handler(_: str, context: CommandContext) -> CommandResult:
        del context
        return CommandResult(
            message=(
                "QuestorHarness quickstart:\n"
                "1. Ask for a coding task in plain language.\n"
                "2. Use /help to inspect commands.\n"
                "3. Use /doctor to inspect runtime state.\n"
                "4. Use /tasks for background work and /memory for project memory.\n"
                "5. Use /login to store an API key if needed."
            )
        )

    registry.register(
        SlashCommand(
            "login",
            "Show auth status or store an API key",
            _login_handler,
            remote_invocable=False,
            remote_admin_opt_in=True,
        )
    )

    registry.register(
        SlashCommand(
            "logout",
            "Clear the stored API key",
            _logout_handler,
            remote_invocable=False,
            remote_admin_opt_in=True,
        )
    )

    registry.register(SlashCommand("feedback", "Save CLI feedback to the local feedback log", _feedback_handler))

    registry.register(SlashCommand("onboarding", "Show the quickstart guide", _onboarding_handler))



def register_skill_commands(registry: CommandRegistry) -> None:
    """Register user-invocable skill commands."""

    async def _skills_handler(args: str, context: CommandContext) -> CommandResult:
        skill_registry = load_skill_registry(
            context.cwd,
            extra_skill_dirs=context.extra_skill_dirs,
            extra_plugin_roots=context.extra_plugin_roots,
        )
        if args:
            skill = skill_registry.get(args)
            if skill is None:
                return CommandResult(message=f"Skill not found: {args}")
            return CommandResult(message=skill.content)
        skills = skill_registry.list_skills()
        if not skills:
            return CommandResult(message="No skills available.")
        lines = ["Available skills:"]
        for skill in skills:
            source = f" [{skill.source}]"
            path = f" {skill.path}" if skill.path else ""
            command_name = _skill_command_name(skill)
            slash = f" /{command_name}" if skill.user_invocable and _is_valid_skill_command_name(command_name) else ""
            display = f" ({skill.display_name})" if skill.display_name else ""
            lines.append(f"- {command_name}{display}{source}{path}{slash}: {skill.description}")
        return CommandResult(message="\n".join(lines))

    registry.register(SlashCommand("skills", "List or show available skills", _skills_handler))

    _register_user_invocable_skill_commands(registry)



def register_config_commands(registry: CommandRegistry) -> None:
    """Register the /config command."""

    async def _config_handler(args: str, context: CommandContext) -> CommandResult:
        del context
        settings = load_settings()
        tokens = args.split(maxsplit=2)
        if not tokens or tokens[0] == "show":
            return CommandResult(message=_settings_json_for_display(settings))
        if tokens[0] == "set" and len(tokens) == 3:
            key, value = tokens[1], tokens[2]
            if key not in Settings.model_fields:
                return CommandResult(message=f"Unknown config key: {key}")
            try:
                coerced = _coerce_setting_value(settings, key, value)
            except ValueError as exc:
                return CommandResult(message=str(exc))
            setattr(settings, key, coerced)
            save_settings(settings)
            return CommandResult(message=f"Updated {key}")
        return CommandResult(message="Usage: /config [show|set KEY VALUE]")

    registry.register(
        SlashCommand(
            "config",
            "Show or update configuration",
            _config_handler,
            remote_invocable=False,
            remote_admin_opt_in=True,
        )
    )
