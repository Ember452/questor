"""Load MCP server config from settings and plugins."""

from __future__ import annotations

from typing import Protocol

from questorharness.contracts.mcp import McpServerConfig


class PluginManifestPort(Protocol):
    """Subset of a plugin manifest needed for MCP server names."""

    name: str


class PluginMcpSource(Protocol):
    """Subset of a loaded plugin needed to merge MCP server configs."""

    enabled: bool
    manifest: PluginManifestPort
    mcp_servers: dict[str, McpServerConfig]


def load_mcp_server_configs(settings, plugins: list[PluginMcpSource]) -> dict[str, object]:
    """Merge settings and plugin MCP server configs."""
    servers = dict(settings.mcp_servers)
    for plugin in plugins:
        if not plugin.enabled:
            continue
        for name, config in plugin.mcp_servers.items():
            servers.setdefault(f"{plugin.manifest.name}:{name}", config)
    return servers

# questor: allow R7 -- until W8 adds the mirror test
