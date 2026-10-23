"""Slash command registry and the ordered list of built-in command families.

The registry type lives in :mod:`questorharness.commands.types`; each command
family lives in :mod:`questorharness.commands.families`.  This module owns the
one thing that must stay global: the order in which families are registered,
because ``/help`` and remote listings preserve registration order.
"""

from __future__ import annotations

from typing import Iterable

from questorharness.capabilities.skills import load_skill_registry
from questorharness.commands.families.account import (
    register_account_commands,
    register_config_commands,
    register_skill_commands,
)
from questorharness.commands.families.agents import register_agents_commands
from questorharness.commands.families.appearance import register_appearance_commands
from questorharness.commands.families.diagnostics import (
    register_diagnostics_commands,
    register_settings_display_commands,
)
from questorharness.commands.families.memory import register_memory_commands
from questorharness.commands.families.model import register_model_commands
from questorharness.commands.families.plugin_management import register_plugin_management_commands
from questorharness.commands.families.plugins import register_plugin_commands
from questorharness.commands.families.policy import register_policy_commands
from questorharness.commands.families.project import (
    register_git_commands,
    register_project_context_commands,
)
from questorharness.commands.families.session import register_session_commands
from questorharness.commands.families.workspace import register_workspace_commands
from questorharness.commands.helpers import (
    _is_valid_skill_command_name,
    _make_skill_slash_command,
    _skill_command_name,
)
from questorharness.commands.types import (
    CommandContext,
    CommandRegistry,
    CommandResult,
    MemoryCommandBackend,
    SlashCommand,
)
from questorharness.plugins.models import PluginCommandDefinition

__all__ = [
    "CommandContext",
    "CommandRegistry",
    "CommandResult",
    "MemoryCommandBackend",
    "SlashCommand",
    "create_default_command_registry",
    "lookup_skill_slash_command",
]


def lookup_skill_slash_command(raw_input: str, context: CommandContext) -> tuple[SlashCommand, str] | None:
    """Resolve a user-invocable skill slash command for the active context.

    This is a runtime fallback for skills that are only visible after the
    active cwd, questor workspace, or plugin roots are known. Unknown slash
    commands still fall through to the normal agent prompt path.
    """
    if not raw_input.startswith("/"):
        return None
    name, _, args = raw_input[1:].partition(" ")
    name = name.strip()
    if not _is_valid_skill_command_name(name):
        return None
    skill_registry = load_skill_registry(
        context.cwd,
        extra_skill_dirs=context.extra_skill_dirs,
        extra_plugin_roots=context.extra_plugin_roots,
    )
    skill = skill_registry.get(name)
    if skill is None or not skill.user_invocable:
        return None
    command_name = _skill_command_name(skill)
    if not _is_valid_skill_command_name(command_name):
        return None
    return _make_skill_slash_command(command_name, f"Invoke the {command_name} skill"), args.strip()


def register_builtin_commands(
    registry: CommandRegistry,
    plugin_commands: Iterable[PluginCommandDefinition] | None = None,
) -> None:
    """Register every built-in family in the order users see in ``/help``."""
    register_session_commands(registry)
    register_memory_commands(registry)
    register_workspace_commands(registry)
    register_account_commands(registry)
    register_skill_commands(registry)
    register_config_commands(registry)
    register_plugin_management_commands(registry)
    register_policy_commands(registry)
    register_model_commands(registry)
    register_appearance_commands(registry)
    register_diagnostics_commands(registry)
    register_git_commands(registry)
    register_project_context_commands(registry)
    register_settings_display_commands(registry)
    register_agents_commands(registry)
    register_plugin_commands(registry, plugin_commands)


def create_default_command_registry(
    plugin_commands: Iterable[PluginCommandDefinition] | None = None,
) -> CommandRegistry:
    """Create the built-in command registry."""
    registry = CommandRegistry()
    register_builtin_commands(registry, plugin_commands)
    return registry
