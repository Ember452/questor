"""Register environment diagnostics. Register read-only settings, release-notes and upgrade help."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path
from questorharness.capabilities.memory import get_project_memory_dir
from questorharness.config.settings import load_settings
from questorharness.platform.paths import get_config_dir, get_feedback_log_path, get_project_config_dir
from questorharness.providers.auth.auth_manager import AuthManager

from questorharness.commands.models import (
    CommandContext,
    CommandRegistry,
    CommandResult,
    SlashCommand,
)


def register_diagnostics_commands(registry: CommandRegistry) -> None:
    """Register environment diagnostics."""

    async def _doctor_handler(_: str, context: CommandContext) -> CommandResult:
        settings = load_settings()
        manager = AuthManager(settings)
        active_profile_name, active_profile = settings.resolve_profile()
        memory_dir = get_project_memory_dir(context.cwd)
        state = context.app_state.get() if context.app_state is not None else None
        lines = [
            "Doctor summary:",
            f"- cwd: {context.cwd}",
            f"- active_profile: {active_profile_name}",
            f"- model: {settings.model}",
            f"- provider_workflow: {active_profile.label}",
            f"- auth_source: {active_profile.auth_source}",
            f"- permission_mode: {state.permission_mode if state is not None else settings.permission.mode}",
            f"- theme: {state.theme if state is not None else settings.theme}",
            f"- output_style: {state.output_style if state is not None else settings.output_style}",
            f"- vim_mode: {'on' if (state.vim_enabled if state is not None else settings.vim_mode) else 'off'}",
            f"- voice_mode: {'on' if (state.voice_enabled if state is not None else settings.voice_mode) else 'off'}",
            f"- effort: {state.effort if state is not None else settings.effort}",
            f"- passes: {state.passes if state is not None else settings.passes}",
            f"- memory_dir: {memory_dir}",
            f"- plugin_count: {max(len(context.plugin_summary.splitlines()) - 1, 0) if context.plugin_summary else 0}",
            f"- mcp_configured: {'yes' if context.mcp_summary and 'No MCP' not in context.mcp_summary else 'no'}",
            f"- auth_configured: {'yes' if manager.get_profile_statuses()[active_profile_name]['configured'] else 'no'}",
        ]
        return CommandResult(message="\n".join(lines))

    registry.register(SlashCommand("doctor", "Show environment diagnostics", _doctor_handler))



def register_settings_display_commands(registry: CommandRegistry) -> None:
    """Register read-only settings, release-notes and upgrade help."""

    async def _privacy_settings_handler(_: str, context: CommandContext) -> CommandResult:
        settings = load_settings()
        session_dir = context.session_backend.get_session_dir(context.cwd)
        lines = [
            "Privacy settings:",
            f"- user_config_dir: {get_config_dir()}",
            f"- project_config_dir: {get_project_config_dir(context.cwd)}",
            f"- session_dir: {session_dir}",
            f"- feedback_log: {get_feedback_log_path()}",
            f"- api_base_url: {settings.base_url or '(default Anthropic-compatible endpoint)'}",
            "- network: enabled only for provider and explicit web/MCP calls",
            "- storage: local files under ~/.questorharness and project .questorharness",
        ]
        return CommandResult(message="\n".join(lines))

    async def _rate_limit_options_handler(_: str, context: CommandContext) -> CommandResult:
        settings = load_settings()
        provider = "moonshot-compatible" if (settings.base_url and "moonshot" in settings.base_url) else "anthropic-compatible"
        lines = [
            "Rate limit options:",
            f"- provider: {provider}",
            "- reduce /passes or switch /effort low for lighter requests",
            "- enable /fast for shorter responses and less tool churn",
            "- use /compact to shrink long transcripts before retrying",
            "- prefer background /tasks for long-running local work",
        ]
        return CommandResult(message="\n".join(lines))

    async def _release_notes_handler(_: str, context: CommandContext) -> CommandResult:
        path = Path(context.cwd) / "RELEASE_NOTES.md"
        if path.exists():
            return CommandResult(message=path.read_text(encoding="utf-8"))
        return CommandResult(
            message=(
                "# Release Notes\n\n"
                "- React TUI is now the default `oh` interface.\n"
                "- Added richer session, files, bridge, agent, copy, rewind, effort, passes, and privacy commands.\n"
                "- Expanded real-model validation across tools, MCP, tasks, plugins, notebook, LSP, cron, and worktree flows.\n"
            )
        )

    async def _upgrade_handler(_: str, context: CommandContext) -> CommandResult:
        del context
        try:
            version = importlib.metadata.version("questorharness")
        except importlib.metadata.PackageNotFoundError:
            version = "0.1.7"
        return CommandResult(
            message=(
                f"Current version: {version}\n"
                "Upgrade instructions:\n"
                "- uv sync --extra dev\n"
                "- uv pip install -e .\n"
                "- npm --prefix frontend/terminal install"
            )
        )

    registry.register(SlashCommand("privacy-settings", "Show local privacy and storage settings", _privacy_settings_handler))

    registry.register(SlashCommand("rate-limit-options", "Show ways to reduce provider rate pressure", _rate_limit_options_handler))

    registry.register(SlashCommand("release-notes", "Show recent QuestorHarness release notes", _release_notes_handler))

    registry.register(SlashCommand("upgrade", "Show upgrade instructions", _upgrade_handler))

# questor: allow R7 -- until W8 adds the mirror test
