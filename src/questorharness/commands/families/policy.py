"""Register permission-mode commands."""

from __future__ import annotations

from questorharness.capabilities.policy import PermissionChecker, PermissionMode
from questorharness.config.settings import load_settings, save_settings

from questorharness.commands.models import (
    CommandContext,
    CommandRegistry,
    CommandResult,
    SlashCommand,
)


def register_policy_commands(registry: CommandRegistry) -> None:
    """Register permission-mode commands."""

    _MODE_LABELS = {"default": "Default", "plan": "Plan Mode", "full_auto": "Auto"}

    async def _permissions_handler(args: str, context: CommandContext) -> CommandResult:
        settings = load_settings()
        tokens = args.split()
        if not tokens or tokens[0] == "show":
            permission = settings.permission
            label = _MODE_LABELS.get(permission.mode.value, permission.mode.value)
            return CommandResult(
                message=(
                    f"Mode: {label}\n"
                    f"Allowed tools: {permission.allowed_tools}\n"
                    f"Denied tools: {permission.denied_tools}"
                )
            )
        target_mode: str | None = None
        if tokens[0] == "set" and len(tokens) == 2:
            target_mode = tokens[1]
        elif len(tokens) == 1 and tokens[0] in _MODE_LABELS:
            target_mode = tokens[0]
        if target_mode is not None:
            settings.permission.mode = PermissionMode(target_mode)
            save_settings(settings)
            context.engine.set_permission_checker(PermissionChecker(settings.permission))
            if context.app_state is not None:
                context.app_state.set(permission_mode=settings.permission.mode.value)
            label = _MODE_LABELS.get(target_mode, target_mode)
            return CommandResult(message=f"Permission mode set to {label}", refresh_runtime=True)
        return CommandResult(message="Usage: /permissions [show|default|full_auto|plan]")

    async def _plan_handler(args: str, context: CommandContext) -> CommandResult:
        settings = load_settings()
        mode = args.strip() or "on"
        if mode in {"on", "enter"}:
            settings.permission.mode = PermissionMode.PLAN
            save_settings(settings)
            context.engine.set_permission_checker(PermissionChecker(settings.permission))
            if context.app_state is not None:
                context.app_state.set(permission_mode=settings.permission.mode.value)
            return CommandResult(message="Plan mode enabled.", refresh_runtime=True)
        if mode in {"off", "exit"}:
            settings.permission.mode = PermissionMode.DEFAULT
            save_settings(settings)
            context.engine.set_permission_checker(PermissionChecker(settings.permission))
            if context.app_state is not None:
                context.app_state.set(permission_mode=settings.permission.mode.value)
            return CommandResult(message="Plan mode disabled.", refresh_runtime=True)
        return CommandResult(message="Usage: /plan [on|off]")

    registry.register(
        SlashCommand(
            "permissions",
            "Show or update permission mode; Tab in the TUI opens the mode picker",
            _permissions_handler,
            remote_invocable=False,
            remote_admin_opt_in=True,
        )
    )

    registry.register(
        SlashCommand(
            "plan",
            "Toggle plan permission mode; /permissions default|full_auto exits plan explicitly",
            _plan_handler,
            remote_invocable=False,
            remote_admin_opt_in=True,
        )
    )

# questor: allow R7 -- until W8 adds the mirror test
