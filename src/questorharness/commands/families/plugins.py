"""Plugin-contributed slash commands."""

from __future__ import annotations

from questorharness.commands.helpers import _render_plugin_command_prompt
from questorharness.plugins.types import PluginCommandDefinition
from typing import Iterable

from questorharness.commands.types import (
    CommandContext,
    CommandRegistry,
    CommandResult,
    SlashCommand,
)


def register_plugin_commands(
    registry: CommandRegistry,
    plugin_commands: Iterable[PluginCommandDefinition] | None,
) -> None:
    """Register user-invocable plugin commands."""

    for plugin_command in plugin_commands or ():
        if not plugin_command.user_invocable:
            continue

        async def _plugin_command_handler(
            args: str,
            context: CommandContext,
            *,
            command: PluginCommandDefinition = plugin_command,
        ) -> CommandResult:
            prompt = _render_plugin_command_prompt(
                command,
                args,
                getattr(context, "session_id", None),
            )
            if command.disable_model_invocation:
                return CommandResult(message=prompt)
            return CommandResult(
                submit_prompt=prompt,
                submit_model=command.model,
            )

        registry.register(
            SlashCommand(
                plugin_command.name,
                plugin_command.description,
                _plugin_command_handler,
            )
        )

# questor: allow R7 -- until W8 adds the mirror test
