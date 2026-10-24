"""Register MCP and plugin management commands."""

from __future__ import annotations

from questorharness.config.settings import load_settings, save_settings
from questorharness.plugins import load_plugins
from questorharness.plugins.installer import install_plugin_from_path, uninstall_plugin

from questorharness.commands.models import (
    CommandContext,
    CommandRegistry,
    CommandResult,
    SlashCommand,
)


def register_plugin_management_commands(registry: CommandRegistry) -> None:
    """Register MCP and plugin management commands."""

    async def _reload_plugins_handler(_: str, context: CommandContext) -> CommandResult:
        settings = load_settings()
        plugins = load_plugins(settings, context.cwd, extra_roots=context.extra_plugin_roots)
        if not plugins:
            return CommandResult(message="No plugins discovered.")
        lines = ["Reloaded plugins:"]
        for plugin in plugins:
            state = "enabled" if plugin.enabled else "disabled"
            lines.append(f"- {plugin.manifest.name} [{state}]")
        return CommandResult(message="\n".join(lines))

    async def _mcp_handler(args: str, context: CommandContext) -> CommandResult:
        settings = load_settings()
        tokens = args.split()
        if tokens and tokens[0] == "auth" and len(tokens) >= 3:
            server_name = tokens[1]
            config = settings.mcp_servers.get(server_name)
            if config is None:
                return CommandResult(message=f"Unknown MCP server: {server_name}")

            if len(tokens) == 3:
                mode = "bearer"
                key = None
                value = tokens[2]
            elif len(tokens) == 4:
                mode = tokens[2]
                key = None
                value = tokens[3]
            elif len(tokens) == 5:
                mode = tokens[2]
                key = tokens[3]
                value = tokens[4]
            else:
                return CommandResult(
                    message="Usage: /mcp auth SERVER TOKEN | /mcp auth SERVER [bearer|env] VALUE | /mcp auth SERVER header KEY VALUE"
                )

            if hasattr(config, "headers"):
                if mode not in {"bearer", "header"}:
                    return CommandResult(message="HTTP/WS MCP auth supports bearer or header modes.")
                header_key = key or "Authorization"
                header_value = (
                    f"Bearer {value}" if mode == "bearer" and header_key == "Authorization" else value
                )
                headers = dict(getattr(config, "headers", {}) or {})
                headers[header_key] = header_value
                settings.mcp_servers[server_name] = config.model_copy(update={"headers": headers})
            elif hasattr(config, "env"):
                if mode not in {"bearer", "env"}:
                    return CommandResult(message="stdio MCP auth supports bearer or env modes.")
                env_key = key or "MCP_AUTH_TOKEN"
                env_value = f"Bearer {value}" if mode == "bearer" else value
                env = dict(getattr(config, "env", {}) or {})
                env[env_key] = env_value
                settings.mcp_servers[server_name] = config.model_copy(update={"env": env})
            else:
                return CommandResult(message=f"Server {server_name} does not support auth updates")
            save_settings(settings)
            return CommandResult(message=f"Saved MCP auth for {server_name}. Restart session to reconnect.")
        return CommandResult(message=context.mcp_summary or "No MCP servers configured.")

    async def _plugin_handler(args: str, context: CommandContext) -> CommandResult:
        settings = load_settings()
        tokens = args.split()
        if not tokens or tokens[0] == "list":
            return CommandResult(message=context.plugin_summary or "No plugins discovered.")
        if tokens[0] == "enable" and len(tokens) == 2:
            settings.enabled_plugins[tokens[1]] = True
            save_settings(settings)
            return CommandResult(message=f"Enabled plugin '{tokens[1]}'. Restart session to reload.")
        if tokens[0] == "disable" and len(tokens) == 2:
            settings.enabled_plugins[tokens[1]] = False
            save_settings(settings)
            return CommandResult(message=f"Disabled plugin '{tokens[1]}'. Restart session to reload.")
        if tokens[0] == "install" and len(tokens) == 2:
            path = install_plugin_from_path(tokens[1])
            return CommandResult(message=f"Installed plugin to {path}")
        if tokens[0] == "uninstall" and len(tokens) == 2:
            try:
                removed = uninstall_plugin(tokens[1])
            except ValueError:
                return CommandResult(message=f"Invalid plugin name '{tokens[1]}'")
            if removed:
                return CommandResult(message=f"Uninstalled plugin '{tokens[1]}'")
            return CommandResult(message=f"Plugin '{tokens[1]}' not found")
        plugins = load_plugins(settings, context.cwd, extra_roots=context.extra_plugin_roots)
        if plugins:
            return CommandResult(message=context.plugin_summary)
        return CommandResult(message="Usage: /plugin [list|enable NAME|disable NAME|install PATH|uninstall NAME]")

    registry.register(
        SlashCommand(
            "mcp",
            "Show MCP status",
            _mcp_handler,
            remote_invocable=False,
            remote_admin_opt_in=True,
        )
    )

    registry.register(
        SlashCommand(
            "plugin",
            "Manage plugins",
            _plugin_handler,
            remote_invocable=False,
            remote_admin_opt_in=True,
        )
    )

    registry.register(
        SlashCommand(
            "reload-plugins",
            "Reload plugin discovery for this workspace",
            _reload_plugins_handler,
            remote_invocable=False,
            remote_admin_opt_in=True,
        )
    )

# questor: allow R7 -- until W8 adds the mirror test
