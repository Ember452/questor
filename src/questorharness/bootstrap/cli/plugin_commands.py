"""``questorharness plugin`` command group."""

from __future__ import annotations

from pathlib import Path

import typer

plugin_app = typer.Typer(name="plugin", help="Manage plugins")


@plugin_app.command("list")
def plugin_list() -> None:
    """List installed plugins."""
    from questorharness.config import load_settings
    from questorharness.plugins import load_plugins

    settings = load_settings()
    plugins = load_plugins(settings, str(Path.cwd()))
    if not plugins:
        print("No plugins installed.")
        return
    for plugin in plugins:
        status = "enabled" if plugin.enabled else "disabled"
        print(f"  {plugin.name} [{status}] - {plugin.description or ''}")


@plugin_app.command("install")
def plugin_install(
    source: str = typer.Argument(..., help="Plugin source (path or URL)"),
) -> None:
    """Install a plugin from a source path."""
    from questorharness.plugins.installer import install_plugin_from_path

    result = install_plugin_from_path(source)
    print(f"Installed plugin: {result}")


@plugin_app.command("uninstall")
def plugin_uninstall(
    name: str = typer.Argument(..., help="Plugin name to uninstall"),
) -> None:
    """Uninstall a plugin."""
    from questorharness.plugins.installer import uninstall_plugin

    try:
        uninstall_plugin(name)
    except ValueError as exc:
        raise typer.BadParameter("invalid plugin name") from exc
    print(f"Uninstalled plugin: {name}")

# questor: allow R7 -- until W8 adds the mirror test
