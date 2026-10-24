"""Mirror test for ``plugins/models.py`` (plan 01, R7)."""

from __future__ import annotations

from pathlib import Path

from questorharness.plugins.models import LoadedPlugin, PluginCommandDefinition
from questorharness.plugins.schemas import PluginManifest


def _manifest(name: str = "demo") -> PluginManifest:
    return PluginManifest(name=name, description="a demo plugin")


def test_plugin_command_defaults_to_plugin_source_and_skill_false() -> None:
    command = PluginCommandDefinition(name="deploy", description="deploy it", content="body")

    assert command.source == "plugin"
    assert command.is_skill is False
    assert command.user_invocable is True
    assert command.disable_model_invocation is False
    assert command.path is None and command.argument_hint is None and command.effort is None


def test_plugin_command_can_carry_optional_metadata() -> None:
    command = PluginCommandDefinition(
        name="deploy",
        description="d",
        content="c",
        argument_hint="[env]",
        effort="high",
        version="1.2",
        is_skill=True,
        display_name="Deploy",
    )

    assert (command.argument_hint, command.effort, command.version) == ("[env]", "high", "1.2")
    assert (command.is_skill, command.display_name) == (True, "Deploy")


def test_loaded_plugin_name_and_description_come_from_the_manifest() -> None:
    plugin = LoadedPlugin(manifest=_manifest("weather"), path=Path("/plugins/weather"), enabled=True)

    assert plugin.name == "weather"
    assert plugin.description == "a demo plugin"


def test_loaded_plugin_contributions_start_empty() -> None:
    first = LoadedPlugin(manifest=_manifest("a"), path=Path("/a"), enabled=False)
    second = LoadedPlugin(manifest=_manifest("b"), path=Path("/b"), enabled=False)

    assert (first.skills, first.commands, first.agents, first.tools) == ([], [], [], [])
    assert first.hooks == {} and first.mcp_servers == {}
    # Independent collections per instance: one must not see the other's additions.
    first.commands.append(PluginCommandDefinition(name="x", description="d", content="c"))
    assert second.commands == []


def test_manifest_object_is_reused_not_copied() -> None:
    manifest = _manifest("shared")
    plugin = LoadedPlugin(manifest=manifest, path=Path("/p"), enabled=True)

    assert plugin.manifest is manifest
