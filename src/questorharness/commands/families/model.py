"""Register model, provider and reasoning-effort commands."""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from questorharness.capabilities.context.prompts import build_runtime_system_prompt
from questorharness.config.settings import display_model_setting, load_settings, save_settings
from questorharness.providers.auth.manager import AuthManager
from questorharness.providers.llm.provider import auth_status, detect_provider

from questorharness.commands.types import (
    CommandContext,
    CommandRegistry,
    CommandResult,
    SlashCommand,
)

if TYPE_CHECKING:
    from questorharness.config.settings import ProviderProfile


def register_model_commands(registry: CommandRegistry) -> None:
    """Register model, provider and reasoning-effort commands."""

    async def _fast_handler(args: str, context: CommandContext) -> CommandResult:
        settings = load_settings()
        current = (
            context.app_state.get().fast_mode
            if context.app_state is not None
            else settings.fast_mode
        )
        action = args.strip() or "show"
        if action == "show":
            return CommandResult(message=f"Fast mode: {'on' if current else 'off'}")
        enabled = {"on": True, "off": False, "toggle": not current}.get(action)
        if enabled is None:
            return CommandResult(message="Usage: /fast [show|on|off|toggle]")
        settings.fast_mode = enabled
        save_settings(settings)
        if context.app_state is not None:
            context.app_state.set(fast_mode=enabled)
        return CommandResult(message=f"Fast mode {'enabled' if enabled else 'disabled'}.")

    async def _effort_handler(args: str, context: CommandContext) -> CommandResult:
        settings = load_settings()
        current = context.app_state.get().effort if context.app_state is not None else settings.effort
        value = args.strip() or "show"
        if value == "show":
            return CommandResult(message=f"Reasoning effort: {current}")
        if value == "max":
            value = "xhigh"
        if value not in {"low", "medium", "high", "xhigh"}:
            return CommandResult(message="Usage: /effort [show|low|medium|high|xhigh]")
        settings.effort = value
        save_settings(settings)
        context.engine.set_effort(value)
        context.engine.set_system_prompt(
            build_runtime_system_prompt(
                settings,
                cwd=context.cwd,
                include_project_memory=context.include_project_memory,
            )
        )
        if context.app_state is not None:
            context.app_state.set(effort=value)
        return CommandResult(message=f"Reasoning effort set to {value}.")

    async def _passes_handler(args: str, context: CommandContext) -> CommandResult:
        settings = load_settings()
        current = context.app_state.get().passes if context.app_state is not None else settings.passes
        value = args.strip() or "show"
        if value == "show":
            return CommandResult(message=f"Passes: {current}")
        try:
            passes = max(1, min(int(value), 8))
        except ValueError:
            return CommandResult(message="Usage: /passes [show|COUNT]")
        settings.passes = passes
        save_settings(settings)
        context.engine.set_system_prompt(
            build_runtime_system_prompt(
                settings,
                cwd=context.cwd,
                include_project_memory=context.include_project_memory,
            )
        )
        if context.app_state is not None:
            context.app_state.set(passes=passes)
        return CommandResult(message=f"Pass count set to {passes}.")

    async def _turns_handler(args: str, context: CommandContext) -> CommandResult:
        settings = load_settings()
        engine_turns = "unlimited" if context.engine.max_turns is None else str(context.engine.max_turns)
        tokens = args.split()
        if not tokens or tokens[0] == "show":
            return CommandResult(
                message=(
                    f"Max turns (engine): {engine_turns}\n"
                    f"Max turns (config): {settings.max_turns}\n"
                    "Usage: /turns [show|unlimited|COUNT]"
                )
            )
        if tokens[0] == "set" and len(tokens) == 2:
            raw = tokens[1]
        elif len(tokens) == 1:
            raw = tokens[0]
        else:
            return CommandResult(message="Usage: /turns [show|unlimited|COUNT]")
        if raw.lower() == "unlimited":
            context.engine.set_max_turns(None)
            return CommandResult(
                message=(
                    "Max turns set to unlimited for this session. "
                    f"Saved config remains {settings.max_turns}."
                )
            )
        try:
            turns = int(raw)
        except ValueError:
            return CommandResult(message="Usage: /turns [show|unlimited|COUNT]")
        turns = max(1, min(turns, 512))
        settings.max_turns = turns
        save_settings(settings)
        context.engine.set_max_turns(turns)
        return CommandResult(message=f"Max turns set to {turns}.")

    async def _continue_handler(args: str, context: CommandContext) -> CommandResult:
        raw = args.strip()
        if not context.engine.has_pending_continuation():
            return CommandResult(message="Nothing to continue (no pending tool results).")

        turns: int | None = None
        if raw:
            tokens = raw.split()
            if tokens[0] == "set" and len(tokens) == 2:
                raw = tokens[1]
            try:
                turns = int(raw)
            except ValueError:
                return CommandResult(message="Usage: /continue [COUNT]")
            turns = max(1, min(turns, 512))

        return CommandResult(
            message="Continuing pending tool loop...",
            continue_pending=True,
            continue_turns=turns,
        )

    async def _stop_handler(_: str, _context: CommandContext) -> CommandResult:
        return CommandResult(
            message=(
                "No active turn is running in this command handler. "
                "While the TUI is running, type /stop or press Esc/Ctrl+C to interrupt the current turn. "
                "In questor remote channels, send /stop."
            )
        )

    def _dedupe_model_values(values: Iterable[str]) -> list[str]:
        models: list[str] = []
        seen: set[str] = set()
        for value in values:
            model = value.strip()
            if not model or model in seen:
                continue
            models.append(model)
            seen.add(model)
        return models

    def _seed_model_values(profile: "ProviderProfile") -> list[str]:
        existing = _dedupe_model_values(profile.allowed_models)
        if existing:
            return existing
        return _dedupe_model_values([display_model_setting(profile)])

    def _format_model_status(active_profile: str, profile: "ProviderProfile") -> str:
        lines = [
            f"Model: {display_model_setting(profile)}",
            f"Profile: {active_profile}",
        ]
        if profile.allowed_models:
            lines.append("Available models:")
            lines.extend(f"- {model}" for model in profile.allowed_models)
        else:
            lines.append("Available models: unrestricted for this profile")
            lines.append("Use /model add MODEL to pin switchable models for the TUI selector.")
        return "\n".join(lines)

    async def _model_handler(args: str, context: CommandContext) -> CommandResult:
        settings = load_settings()
        manager = AuthManager(settings)
        active_profile = manager.get_active_profile()
        _, profile = settings.resolve_profile(active_profile)
        tokens = args.split(maxsplit=1)
        if not tokens or tokens[0] == "show":
            return CommandResult(message=_format_model_status(active_profile, profile))
        if tokens[0] == "list":
            if profile.allowed_models:
                return CommandResult(
                    message=(
                        f"Switchable models for profile '{active_profile}':\n"
                        + "\n".join(f"- {model}" for model in profile.allowed_models)
                    )
                )
            return CommandResult(
                message=(
                    f"Profile '{active_profile}' has no pinned model list. "
                    "Any model value is accepted. Use /model add MODEL to add one."
                )
            )
        if tokens[0] == "add" and len(tokens) == 2:
            model_name = tokens[1].strip()
            models = _dedupe_model_values([*_seed_model_values(profile), model_name])
            if not model_name:
                return CommandResult(message="Usage: /model add MODEL")
            manager.update_profile(active_profile, allowed_models=models)
            return CommandResult(
                message=f"Added model '{model_name}' to profile '{active_profile}'.",
                refresh_runtime=True,
            )
        if tokens[0] == "add":
            return CommandResult(message="Usage: /model add MODEL")
        if tokens[0] in {"remove", "rm"} and len(tokens) == 2:
            model_name = tokens[1].strip()
            models = [model for model in _dedupe_model_values(profile.allowed_models) if model != model_name]
            if len(models) == len(_dedupe_model_values(profile.allowed_models)):
                return CommandResult(message=f"Model '{model_name}' is not pinned for profile '{active_profile}'.")
            reset_current = (profile.last_model or "").strip() == model_name
            manager.update_profile(
                active_profile,
                allowed_models=models,
                last_model="" if reset_current else None,
            )
            updated = load_settings()
            if reset_current:
                context.engine.set_model(updated.model)
                if context.app_state is not None:
                    updated_profile = updated.resolve_profile()[1]
                    context.app_state.set(model=display_model_setting(updated_profile))
            return CommandResult(
                message=f"Removed model '{model_name}' from profile '{active_profile}'.",
                refresh_runtime=True,
            )
        if tokens[0] in {"remove", "rm"}:
            return CommandResult(message="Usage: /model remove MODEL")
        if tokens[0] == "clear":
            manager.update_profile(active_profile, allowed_models=[])
            return CommandResult(
                message=f"Cleared pinned models for profile '{active_profile}'. Any model value is now accepted.",
                refresh_runtime=True,
            )
        if tokens[0] == "set" and len(tokens) == 2:
            model_name = tokens[1].strip()
        elif args.strip():
            model_name = args.strip()
        else:
            model_name = None
        if model_name:
            if profile.allowed_models and model_name.lower() != "default" and model_name not in profile.allowed_models:
                allowed = ", ".join(profile.allowed_models)
                return CommandResult(message=f"Model '{model_name}' is not allowed for profile '{active_profile}'. Allowed models: {allowed}")
            if model_name.lower() == "default":
                manager.update_profile(active_profile, last_model="")
                message = "Model reset to default."
            else:
                manager.update_profile(active_profile, last_model=model_name)
                message = f"Model set to {model_name}."
            updated = load_settings()
            context.engine.set_model(updated.model)
            if context.app_state is not None:
                updated_profile = updated.resolve_profile()[1]
                context.app_state.set(model=display_model_setting(updated_profile))
            return CommandResult(message=message, refresh_runtime=True)
        return CommandResult(message="Usage: /model [show|list|add MODEL|remove MODEL|clear|MODEL]")

    async def _provider_handler(args: str, context: CommandContext) -> CommandResult:
        manager = AuthManager()
        profiles = manager.get_profile_statuses()
        tokens = args.split()
        if not tokens or tokens[0] == "show":
            active_name = manager.get_active_profile()
            active = profiles[active_name]
            lines = [
                f"Active profile: {active_name}",
                f"Label: {active['label']}",
                f"Provider: {active['provider']}",
                f"Auth source: {active['auth_source']}",
                f"Configured: {'yes' if active['configured'] else 'no'}",
                f"Base URL: {active['base_url'] or '(default)'}",
                f"Model: {active['model']}",
            ]
            return CommandResult(message="\n".join(lines))
        if tokens[0] == "list":
            lines = ["Provider profiles:"]
            for name, info in profiles.items():
                marker = "*" if info["active"] else " "
                configured = "configured" if info["configured"] else "missing auth"
                lines.append(f"{marker} {name} [{configured}] {info['label']} -> {info['model']}")
            return CommandResult(message="\n".join(lines))
        target = tokens[1] if tokens[0] == "use" and len(tokens) == 2 else (tokens[0] if len(tokens) == 1 else None)
        if target is None:
            return CommandResult(message="Usage: /provider [show|list|PROFILE]")
        manager.use_profile(target)
        updated = load_settings()
        profile = updated.resolve_profile()[1]
        context.engine.set_model(updated.model)
        if context.app_state is not None:
            context.app_state.set(
                model=display_model_setting(profile),
                provider=detect_provider(updated).name,
                auth_status=auth_status(updated),
                base_url=updated.base_url or "",
            )
        return CommandResult(
            message=f"Switched provider profile to {target} ({profile.label}).",
            refresh_runtime=True,
        )

    registry.register(SlashCommand("fast", "Show or update fast mode", _fast_handler))

    registry.register(SlashCommand("effort", "Show or update reasoning effort", _effort_handler))

    registry.register(SlashCommand("passes", "Show or update reasoning pass count", _passes_handler))

    registry.register(SlashCommand("turns", "Show or update maximum agentic turn count", _turns_handler))

    registry.register(SlashCommand("continue", "Continue the previous tool loop if it was interrupted", _continue_handler))

    registry.register(SlashCommand("stop", "Interrupt the running turn from TUI/questor channels", _stop_handler))

    registry.register(
        SlashCommand(
            "provider",
            "Show or switch provider profiles",
            _provider_handler,
            remote_invocable=False,
            remote_admin_opt_in=True,
        )
    )

    registry.register(
        SlashCommand(
            "model",
            "Show, switch, or manage profile models",
            _model_handler,
            remote_invocable=False,
            remote_admin_opt_in=True,
        )
    )
