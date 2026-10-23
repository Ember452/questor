"""Register theme, output-style, keybinding and voice commands."""

from __future__ import annotations

from questorharness.config.settings import load_settings, save_settings
from questorharness.output_styles import load_output_styles
from questorharness.providers.llm.provider import detect_provider

from questorharness.commands.types import (
    CommandContext,
    CommandRegistry,
    CommandResult,
    SlashCommand,
)


def register_appearance_commands(registry: CommandRegistry) -> None:
    """Register theme, output-style, keybinding and voice commands."""

    async def _theme_handler(args: str, context: CommandContext) -> CommandResult:
        from questorharness.themes import list_themes, load_theme

        settings = load_settings()
        tokens = args.split(maxsplit=1)
        current = (
            context.app_state.get().theme
            if context.app_state is not None and hasattr(context.app_state.get(), "theme")
            else settings.theme
        )

        if not tokens or tokens[0] == "show":
            try:
                theme = load_theme(current)
                lines = [
                    f"Theme: {theme.name}",
                    f"  Colors:  primary={theme.colors.primary}  secondary={theme.colors.secondary}"
                    f"  accent={theme.colors.accent}  error={theme.colors.error}"
                    f"  muted={theme.colors.muted}",
                    f"           background={theme.colors.background}  foreground={theme.colors.foreground}",
                    f"  Borders: style={theme.borders.style}",
                    f"  Icons:   spinner={theme.icons.spinner}  tool={theme.icons.tool}"
                    f"  error={theme.icons.error}  success={theme.icons.success}"
                    f"  agent={theme.icons.agent}",
                    f"  Layout:  compact={theme.layout.compact}"
                    f"  show_tokens={theme.layout.show_tokens}"
                    f"  show_time={theme.layout.show_time}",
                ]
                return CommandResult(message="\n".join(lines))
            except KeyError:
                return CommandResult(message=f"Theme: {current} (not found)")

        if tokens[0] == "list":
            available = list_themes()
            lines = [f"{'*' if name == current else ' '} {name}" for name in available]
            return CommandResult(message="\n".join(lines))

        if tokens[0] == "set" and len(tokens) == 2:
            name = tokens[1]
        elif len(tokens) == 1 and tokens[0] not in {"list", "preview"}:
            name = tokens[0]
        else:
            name = None
        if name is not None:
            try:
                load_theme(name)
            except KeyError:
                available = list_themes()
                return CommandResult(
                    message=f"Unknown theme: {name!r}. Available: {', '.join(available)}"
                )
            settings.theme = name
            save_settings(settings)
            if context.app_state is not None:
                context.app_state.set(theme=name)
            return CommandResult(message=f"Theme set to {name}")

        if tokens[0] == "preview" and len(tokens) == 2:
            name = tokens[1]
            try:
                theme = load_theme(name)
            except KeyError:
                available = list_themes()
                return CommandResult(
                    message=f"Unknown theme: {name!r}. Available: {', '.join(available)}"
                )
            lines = [
                f"Preview: {theme.name}",
                f"  primary    {theme.colors.primary}",
                f"  secondary  {theme.colors.secondary}",
                f"  accent     {theme.colors.accent}",
                f"  error      {theme.colors.error}",
                f"  muted      {theme.colors.muted}",
                f"  background {theme.colors.background}",
                f"  foreground {theme.colors.foreground}",
                f"  borders    {theme.borders.style}",
                f"  icons      spinner={theme.icons.spinner} tool={theme.icons.tool}"
                f" success={theme.icons.success} error={theme.icons.error}"
                f" agent={theme.icons.agent}",
            ]
            return CommandResult(message="\n".join(lines))

        return CommandResult(message="Usage: /theme [list|show|NAME|preview NAME]")

    async def _output_style_handler(args: str, context: CommandContext) -> CommandResult:
        settings = load_settings()
        tokens = args.split(maxsplit=1)
        styles = load_output_styles()
        available = {style.name: style for style in styles}
        current = (
            context.app_state.get().output_style
            if context.app_state is not None
            else settings.output_style
        )
        if not tokens or tokens[0] == "show":
            return CommandResult(message=f"Output style: {current}")
        if tokens[0] == "list":
            return CommandResult(
                message="\n".join(f"{style.name} [{style.source}]" for style in styles)
            )
        if tokens[0] == "set" and len(tokens) == 2:
            style_name = tokens[1]
        elif len(tokens) == 1 and tokens[0] not in {"list"}:
            style_name = tokens[0]
        else:
            style_name = None
        if style_name is not None:
            if style_name not in available:
                return CommandResult(message=f"Unknown output style: {style_name}")
            settings.output_style = style_name
            save_settings(settings)
            if context.app_state is not None:
                context.app_state.set(output_style=style_name)
            return CommandResult(message=f"Output style set to {style_name}")
        return CommandResult(message="Usage: /output-style [show|list|NAME]")

    async def _keybindings_handler(_: str, context: CommandContext) -> CommandResult:
        from questorharness.keybindings import get_keybindings_path, load_keybindings

        bindings = (
            context.app_state.get().keybindings
            if context.app_state is not None and context.app_state.get().keybindings
            else load_keybindings()
        )
        lines = [f"Keybindings file: {get_keybindings_path()}"]
        lines.extend(f"{key} -> {command}" for key, command in sorted(bindings.items()))
        return CommandResult(message="\n".join(lines))

    async def _vim_handler(args: str, context: CommandContext) -> CommandResult:
        settings = load_settings()
        current = (
            context.app_state.get().vim_enabled
            if context.app_state is not None
            else settings.vim_mode
        )
        action = args.strip() or "show"
        if action == "show":
            return CommandResult(message=f"Vim mode: {'on' if current else 'off'}")
        enabled = {"on": True, "off": False, "toggle": not current}.get(action)
        if enabled is None:
            return CommandResult(message="Usage: /vim [show|on|off|toggle]")
        settings.vim_mode = enabled
        save_settings(settings)
        if context.app_state is not None:
            context.app_state.set(vim_enabled=enabled)
        return CommandResult(message=f"Vim mode {'enabled' if enabled else 'disabled'}.")

    async def _voice_handler(args: str, context: CommandContext) -> CommandResult:
        from questorharness.providers.voice import extract_keyterms, inspect_voice_capabilities

        settings = load_settings()
        diagnostics = inspect_voice_capabilities(detect_provider(settings))
        current = (
            context.app_state.get().voice_enabled
            if context.app_state is not None
            else settings.voice_mode
        )
        tokens = args.split(maxsplit=1)
        if not tokens or tokens[0] == "show":
            return CommandResult(
                message=(
                    f"Voice mode: {'on' if current else 'off'}\n"
                    f"Available: {'yes' if diagnostics.available else 'no'}\n"
                    f"Recorder: {diagnostics.recorder or '(none)'}\n"
                    f"Reason: {diagnostics.reason}"
                )
            )
        if tokens[0] == "keyterms" and len(tokens) == 2:
            keyterms = extract_keyterms(tokens[1])
            return CommandResult(message="\n".join(keyterms) if keyterms else "(no keyterms)")
        enabled = {"on": True, "off": False, "toggle": not current}.get(tokens[0])
        if enabled is None:
            return CommandResult(message="Usage: /voice [show|on|off|toggle|keyterms TEXT]")
        settings.voice_mode = enabled
        save_settings(settings)
        if context.app_state is not None:
            context.app_state.set(
                voice_enabled=enabled,
                voice_available=diagnostics.available,
                voice_reason=diagnostics.reason,
            )
        return CommandResult(message=f"Voice mode {'enabled' if enabled else 'disabled'}.")

    registry.register(SlashCommand("theme", "List, set, show or preview TUI themes", _theme_handler))

    registry.register(SlashCommand("output-style", "Show or update output style", _output_style_handler))

    registry.register(SlashCommand("keybindings", "Show resolved keybindings", _keybindings_handler))

    registry.register(SlashCommand("vim", "Show or update Vim mode", _vim_handler))

    registry.register(SlashCommand("voice", "Show or update voice mode", _voice_handler))

# questor: allow R7 -- until W8 adds the mirror test
