"""Session and core slash commands."""

from __future__ import annotations

from questorharness.capabilities.context.compact import build_post_compact_messages, compact_conversation, compact_messages, estimate_conversation_tokens, summarize_messages
from questorharness.capabilities.context.prompts import build_runtime_system_prompt
from questorharness.commands.memory_commands import _memory_backend_for_context
from questorharness.config.settings import load_settings
from questorharness.providers.auth.auth_manager import AuthManager
from questorharness.runtime.tasks import get_task_manager
import importlib.metadata

from questorharness.commands.models import (
    CommandContext,
    CommandRegistry,
    CommandResult,
    SlashCommand,
)


def register_session_commands(registry: CommandRegistry) -> None:
    """Register session and core commands in their original order."""

    async def _help_handler(_: str, context: CommandContext) -> CommandResult:
        del context
        return CommandResult(message=registry.help_text())

    async def _exit_handler(_: str, context: CommandContext) -> CommandResult:
        del context
        return CommandResult(should_exit=True)

    async def _clear_handler(_: str, context: CommandContext) -> CommandResult:
        context.engine.clear()
        return CommandResult(message="Conversation cleared.", clear_screen=True)

    async def _status_handler(_: str, context: CommandContext) -> CommandResult:
        usage = context.engine.total_usage
        state = context.app_state.get() if context.app_state is not None else None
        manager = AuthManager()
        return CommandResult(
            message=(
                f"Messages: {len(context.engine.messages)}\n"
                f"Usage: input={usage.input_tokens} output={usage.output_tokens}\n"
                f"Profile: {manager.get_active_profile()}\n"
                f"Effort: {state.effort if state is not None else load_settings().effort}\n"
                f"Passes: {state.passes if state is not None else load_settings().passes}"
            )
        )

    async def _version_handler(_: str, context: CommandContext) -> CommandResult:
        del context
        try:
            version = importlib.metadata.version("questorharness")
        except importlib.metadata.PackageNotFoundError:
            version = "0.1.7"
        return CommandResult(message=f"QuestorHarness {version}")

    async def _context_handler(_: str, context: CommandContext) -> CommandResult:
        settings = load_settings()
        prompt = build_runtime_system_prompt(
            settings,
            cwd=context.cwd,
            include_project_memory=context.include_project_memory,
        )
        return CommandResult(message=prompt)

    async def _summary_handler(args: str, context: CommandContext) -> CommandResult:
        max_messages = 8
        if args:
            try:
                max_messages = max(1, int(args))
            except ValueError:
                return CommandResult(message="Usage: /summary [MAX_MESSAGES]")
        summary = summarize_messages(context.engine.messages, max_messages=max_messages)
        return CommandResult(message=summary or "No conversation content to summarize.")

    async def _compact_handler(args: str, context: CommandContext) -> CommandResult:
        preserve_recent = 6
        if args:
            try:
                preserve_recent = max(1, int(args))
            except ValueError:
                return CommandResult(message="Usage: /compact [PRESERVE_RECENT]")
        before = len(context.engine.messages)
        try:
            compacted_result = await compact_conversation(
                context.engine.messages,
                api_client=context.engine.api_client,
                model=context.engine.model,
                system_prompt=context.engine.system_prompt,
                preserve_recent=preserve_recent,
                trigger="manual",
            )
            compacted = build_post_compact_messages(compacted_result)
        except Exception:
            compacted = compact_messages(context.engine.messages, preserve_recent=preserve_recent)
        context.engine.load_messages(compacted)
        return CommandResult(
            message=f"Compacted conversation from {before} messages to {len(compacted)}."
        )

    async def _usage_handler(_: str, context: CommandContext) -> CommandResult:
        usage = context.engine.total_usage
        estimated = estimate_conversation_tokens(context.engine.messages)
        return CommandResult(
            message=(
                f"Actual usage: input={usage.input_tokens} output={usage.output_tokens}\n"
                f"Estimated conversation tokens: {estimated}\n"
                f"Messages: {len(context.engine.messages)}"
            )
        )

    async def _cost_handler(_: str, context: CommandContext) -> CommandResult:
        usage = context.engine.total_usage
        model = context.app_state.get().model if context.app_state is not None else load_settings().model
        estimated_cost = "unavailable"
        if model.startswith("claude-3-5-sonnet"):
            estimated = (usage.input_tokens * 3.0 + usage.output_tokens * 15.0) / 1_000_000
            estimated_cost = f"${estimated:.4f} (estimated)"
        elif model.startswith("claude-3-7-sonnet"):
            estimated = (usage.input_tokens * 3.0 + usage.output_tokens * 15.0) / 1_000_000
            estimated_cost = f"${estimated:.4f} (estimated)"
        elif model.startswith("claude-3-opus"):
            estimated = (usage.input_tokens * 15.0 + usage.output_tokens * 75.0) / 1_000_000
            estimated_cost = f"${estimated:.4f} (estimated)"
        return CommandResult(
            message=(
                f"Model: {model}\n"
                f"Input tokens: {usage.input_tokens}\n"
                f"Output tokens: {usage.output_tokens}\n"
                f"Total tokens: {usage.total_tokens}\n"
                f"Estimated cost: {estimated_cost}"
            )
        )

    async def _stats_handler(_: str, context: CommandContext) -> CommandResult:
        settings = load_settings()
        memory_backend = _memory_backend_for_context(context)
        memory_count = len(memory_backend.list_files())
        task_count = len(get_task_manager().list_tasks())
        tool_count = len(context.tool_registry.list_tools()) if context.tool_registry is not None else 0
        style = settings.output_style
        if context.app_state is not None:
            state = context.app_state.get()
            style = state.output_style
        return CommandResult(
            message=(
                "Session stats:\n"
                f"- messages: {len(context.engine.messages)}\n"
                f"- estimated_tokens: {estimate_conversation_tokens(context.engine.messages)}\n"
                f"- tools: {tool_count}\n"
                f"- memory_files: {memory_count}\n"
                f"- background_tasks: {task_count}\n"
                f"- output_style: {style}"
            )
        )

    registry.register(SlashCommand("help", "Show available commands", _help_handler))
    registry.register(
        SlashCommand("exit", "Exit QuestorHarness", _exit_handler, aliases=("quit",))
    )
    registry.register(SlashCommand("clear", "Clear conversation history", _clear_handler))
    registry.register(SlashCommand("version", "Show the installed QuestorHarness version", _version_handler))
    registry.register(SlashCommand("status", "Show session status", _status_handler))
    registry.register(SlashCommand("context", "Show the active runtime system prompt", _context_handler))
    registry.register(
        SlashCommand(
            "summary",
            "Summarize conversation history",
            _summary_handler,
            remote_invocable=False,
            remote_admin_opt_in=True,
        )
    )
    registry.register(SlashCommand("compact", "Compact older conversation history", _compact_handler))
    registry.register(SlashCommand("cost", "Show token usage and estimated cost", _cost_handler))
    registry.register(SlashCommand("usage", "Show usage and token estimates", _usage_handler))
    registry.register(SlashCommand("stats", "Show session statistics", _stats_handler))

# questor: allow R7 -- until W8 adds the mirror test
