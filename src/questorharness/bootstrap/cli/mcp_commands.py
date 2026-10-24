"""``questorharness mcp`` command group."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

mcp_app = typer.Typer(name="mcp", help="Manage MCP servers")


@mcp_app.command("list")
def mcp_list() -> None:
    """List configured MCP servers."""
    from questorharness.config import load_settings
    from questorharness.plugins import load_plugins
    from questorharness.providers.mcp.config import load_mcp_server_configs

    settings = load_settings()
    plugins = load_plugins(settings, str(Path.cwd()))
    configs = load_mcp_server_configs(settings, plugins)
    if not configs:
        print("No MCP servers configured.")
        return
    for name, cfg in configs.items():
        transport = cfg.get("transport", cfg.get("command", "unknown"))
        print(f"  {name}: {transport}")


@mcp_app.command("add")
def mcp_add(
    name: str = typer.Argument(..., help="Server name"),
    config_json: str = typer.Argument(..., help="Server config as JSON string"),
) -> None:
    """Add an MCP server configuration."""
    from questorharness.config import load_settings, save_settings

    settings = load_settings()
    try:
        cfg = json.loads(config_json)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON: {exc}", file=sys.stderr)
        raise typer.Exit(1)
    if not isinstance(settings.mcp_servers, dict):
        settings.mcp_servers = {}
    settings.mcp_servers[name] = cfg
    save_settings(settings)
    print(f"Added MCP server: {name}")


@mcp_app.command("remove")
def mcp_remove(
    name: str = typer.Argument(..., help="Server name to remove"),
) -> None:
    """Remove an MCP server configuration."""
    from questorharness.config import load_settings, save_settings

    settings = load_settings()
    if not isinstance(settings.mcp_servers, dict) or name not in settings.mcp_servers:
        print(f"MCP server not found: {name}", file=sys.stderr)
        raise typer.Exit(1)
    del settings.mcp_servers[name]
    save_settings(settings)
    print(f"Removed MCP server: {name}")

# questor: allow R7 -- until W8 adds the mirror test
