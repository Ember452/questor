"""Memory and hook inspection slash commands."""

from __future__ import annotations

from datetime import datetime
from questorharness.capabilities.memory import add_memory_entry, get_project_memory_dir, migrate_memory
from questorharness.capabilities.memory.consolidate import diff_memory_dirs, format_memory_diff, latest_memory_backup, read_last_consolidated_at, restore_memory_backup, start_dream_now
from questorharness.capabilities.memory.extract import extract_memories_from_turn
from questorharness.capabilities.memory.schema import is_disabled_metadata, is_memory_expired, split_memory_file
from questorharness.commands.memory_commands import _handle_memory_agent_command, _handle_memory_edit_command, _handle_memory_session_command, _handle_memory_team_command, _handle_memory_validate_command, _memory_backend_for_context, _parse_memory_add_flags, _resolve_memory_entry_path
from questorharness.config.settings import load_settings
from questorharness.runtime.tasks import get_task_manager

from questorharness.commands.models import (
    CommandContext,
    CommandRegistry,
    CommandResult,
    SlashCommand,
)


def register_memory_commands(registry: CommandRegistry) -> None:
    """Register memory and hook inspection commands."""

    async def _dream_handler(args: str, context: CommandContext) -> CommandResult:
        settings = getattr(context.engine, "_settings", None) or load_settings().materialize_active_profile()
        parts = args.split()
        action = parts[0] if parts else "run"
        backend = context.memory_backend if context.memory_backend is not None else None
        memory_dir = backend.get_memory_dir() if backend is not None else get_project_memory_dir(context.cwd)
        session_dir = context.session_backend.get_session_dir(context.cwd)
        app_label = backend.label if backend is not None else "questorharness project memory"
        runner_module = "questor" if backend is not None and "questor" in backend.label.lower() else "questorharness"
        if action == "status":
            last_at = read_last_consolidated_at(context.cwd, memory_dir=memory_dir)
            last = "never" if last_at <= 0 else datetime.fromtimestamp(last_at).isoformat(timespec="seconds")
            return CommandResult(
                message=(
                    f"Auto-dream: {'on' if settings.memory.auto_dream_enabled else 'off'}\n"
                    f"Memory store: {app_label}\n"
                    f"Memory directory: {memory_dir}\n"
                    f"Session directory: {session_dir}\n"
                    f"Last consolidated: {last}"
                )
            )
        if action == "diff":
            target = parts[1] if len(parts) > 1 else "latest"
            task_memory_dir = str(memory_dir)
            backup_dir = ""
            label = target
            if target == "latest":
                latest = latest_memory_backup(memory_dir, app_label=app_label)
                backup_dir = str(latest) if latest is not None else ""
                label = "latest backup"
            else:
                task = get_task_manager().get_task(target)
                if task is not None and task.type == "dream":
                    backup_dir = task.metadata.get("backup_dir", "")
                    task_memory_dir = task.metadata.get("memory_dir", str(memory_dir))
                    label = task.id
            if not backup_dir:
                return CommandResult(message=f"No dream backup found for {target}.")
            diff = diff_memory_dirs(backup_dir, task_memory_dir)
            return CommandResult(
                message=(
                    f"Dream diff for {label}:\n"
                    f"Backup: {backup_dir}\n"
                    f"Memory: {task_memory_dir}\n"
                    f"{format_memory_diff(diff)}"
                )
            )
        if action == "rollback":
            target = parts[1] if len(parts) > 1 else "latest"
            task_memory_dir = str(memory_dir)
            backup_dir = ""
            label = target
            if target == "latest":
                latest = latest_memory_backup(memory_dir, app_label=app_label)
                backup_dir = str(latest) if latest is not None else ""
                label = "latest backup"
            else:
                task = get_task_manager().get_task(target)
                if task is not None and task.type == "dream":
                    backup_dir = task.metadata.get("backup_dir", "")
                    task_memory_dir = task.metadata.get("memory_dir", str(memory_dir))
                    label = task.id
            if not backup_dir:
                return CommandResult(message=f"No dream backup found for {target}.")
            restore_memory_backup(backup_dir, task_memory_dir)
            return CommandResult(message=f"Rolled back memory from backup for {label}: {backup_dir}")
        if action not in {"run", "now", "preview"}:
            return CommandResult(message="Usage: /dream [run|now|preview|status|diff [task_id]|rollback [task_id]]")
        task = await start_dream_now(
            cwd=context.cwd,
            settings=settings,
            model=context.engine.model,
            current_session_id=context.session_id,
            force=True,
            memory_dir=memory_dir,
            session_dir=session_dir,
            app_label=app_label,
            runner_module=runner_module,
            preview=action == "preview",
        )
        if task is None:
            return CommandResult(message="Dream did not start. Memory may be disabled or another dream is running.")
        return CommandResult(
            message=(
                f"Started {'preview ' if action == 'preview' else ''}memory consolidation task {task.id}.\n"
                f"Memory directory: {task.metadata.get('memory_dir', get_project_memory_dir(context.cwd))}\n"
                f"Backup directory: {task.metadata.get('backup_dir', '') or '(preview/no backup)'}\n"
                "Use /tasks or task_output to inspect progress. After completion: /dream diff latest or /dream rollback latest."
            )
        )

    async def _memory_handler(args: str, context: CommandContext) -> CommandResult:
        backend = _memory_backend_for_context(context)
        tokens = args.split(maxsplit=1)
        if not tokens:
            return CommandResult(
                message=(
                    f"Memory store: {backend.label}\n"
                    f"Memory directory: {backend.get_memory_dir()}\n"
                    f"Entrypoint: {backend.get_entrypoint()}\n"
                    "Commands: list, show NAME, add TITLE :: CONTENT, remove NAME, "
                    "edit [NAME], validate, extract, session, team, agent, "
                    "migrate --dry-run, migrate --apply"
                )
            )
        action = tokens[0]
        rest = tokens[1] if len(tokens) == 2 else ""
        if action == "list":
            memory_files = backend.list_files()
            if not memory_files:
                return CommandResult(message="No memory files.")
            return CommandResult(message="\n".join(path.name for path in memory_files))
        if action == "migrate":
            if rest not in {"--dry-run", "--apply"}:
                return CommandResult(
                    message=(
                        "Usage: /memory "
                        "[list|show NAME|add TITLE :: CONTENT|remove NAME|"
                        "migrate --dry-run|migrate --apply]"
                    )
                )
            summary = migrate_memory(
                context.cwd,
                memory_dir=backend.get_memory_dir(),
                default_type=backend.default_type,
                default_category=backend.default_category,
                apply=rest == "--apply",
            )
            mode = "dry run" if summary.dry_run else "applied"
            lines = [
                f"Memory migration {mode}.",
                f"Scanned: {summary.scanned}",
                f"Changed: {summary.changed}",
                f"Unchanged: {summary.unchanged}",
                f"Failed: {summary.failed}",
            ]
            if summary.backup_dir:
                lines.append(f"Backup: {summary.backup_dir}")
            if summary.changed_files:
                lines.append("Changed files: " + ", ".join(summary.changed_files))
            if summary.failed_files:
                lines.append("Failed files: " + ", ".join(summary.failed_files))
            return CommandResult(message="\n".join(lines))
        if action == "show" and rest:
            memory_dir = backend.get_memory_dir()
            path, invalid = _resolve_memory_entry_path(memory_dir, rest)
            if invalid:
                return CommandResult(message="Memory entry path must stay within the configured memory directory.")
            if path is None:
                return CommandResult(message=f"Memory entry not found: {rest}")
            if not path.exists():
                return CommandResult(message=f"Memory entry not found: {rest}")
            content = path.read_text(encoding="utf-8")
            metadata, _, _, _ = split_memory_file(content)
            if is_disabled_metadata(metadata) or is_memory_expired(metadata):
                return CommandResult(message=f"Memory entry not found: {rest}")
            return CommandResult(message=content)
        if action == "add" and rest:
            memory_type, scope, cleaned_rest = _parse_memory_add_flags(rest)
            title, separator, content = cleaned_rest.partition("::")
            if not separator or not title.strip() or not content.strip():
                return CommandResult(message="Usage: /memory add [--type TYPE] [--scope SCOPE] TITLE :: CONTENT")
            if context.memory_backend is None:
                path = add_memory_entry(
                    context.cwd,
                    title.strip(),
                    content.strip(),
                    memory_type=memory_type,
                    scope=scope,
                )
            else:
                path = backend.add_entry(title.strip(), content.strip())
            return CommandResult(message=f"Added memory entry {path.name}")
        if action == "remove" and rest:
            if backend.remove_entry(rest.strip()):
                return CommandResult(message=f"Removed memory entry {rest.strip()}")
            return CommandResult(message=f"Memory entry not found: {rest.strip()}")
        if action == "edit":
            return _handle_memory_edit_command(rest, context, backend)
        if action == "validate":
            return _handle_memory_validate_command(context)
        if action == "extract":
            if context.memory_backend is not None:
                return CommandResult(message="Memory extraction is only supported for QuestorHarness project memory.")
            result = await extract_memories_from_turn(
                cwd=context.cwd,
                api_client=context.engine.api_client,
                model=context.engine.model,
                messages=context.engine.messages,
                max_records=load_settings().memory.auto_extract_max_records,
            )
            if result.skipped:
                return CommandResult(message=f"Memory extraction skipped: {result.reason}")
            return CommandResult(
                message="Memory extraction wrote:\n" + "\n".join(f"- {path}" for path in result.written_paths)
            )
        if action == "session":
            return _handle_memory_session_command(rest, context)
        if action == "team":
            return _handle_memory_team_command(rest, context)
        if action == "agent":
            return _handle_memory_agent_command(rest, context)
        return CommandResult(
            message=(
                "Usage: /memory "
                "[list|show NAME|add TITLE :: CONTENT|remove NAME|edit [NAME]|"
                "validate|extract|session|team|agent|"
                "migrate --dry-run|migrate --apply]"
            )
        )

    async def _hooks_handler(_: str, context: CommandContext) -> CommandResult:
        return CommandResult(message=context.hooks_summary or "No hooks configured.")

    registry.register(SlashCommand("dream", "Consolidate memory", _dream_handler))
    registry.register(SlashCommand("memory", "Inspect and manage project memory", _memory_handler))
    registry.register(SlashCommand("hooks", "Show configured hooks", _hooks_handler))

# questor: allow R7 -- until W8 adds the mirror test
# questor: allow R8 -- refactor the offenders in W8
