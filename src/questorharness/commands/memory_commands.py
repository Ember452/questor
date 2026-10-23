"""Memory subcommands for the slash command registry."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from questorharness.capabilities.memory import (
    add_memory_entry,
    get_memory_entrypoint,
    get_project_memory_dir,
    list_memory_files,
    remove_memory_entry,
    scan_memory_files,
)
from questorharness.capabilities.memory.agent import (
    ensure_agent_memory_vault,
    get_agent_memory_entrypoint,
    initialize_agent_memory_from_snapshot,
)
from questorharness.capabilities.memory.schema import (
    DEFAULT_MEMORY_SCOPE,
    DEFAULT_MEMORY_TYPE,
    MEMORY_TYPES,
    parse_memory_scope,
    parse_memory_type,
)
from questorharness.capabilities.memory.session import (
    get_session_memory_content,
    get_session_memory_path,
    update_session_memory_file,
)
from questorharness.capabilities.memory.team import (
    check_team_memory_secrets,
    ensure_team_memory_vault,
    get_team_memory_dir,
)

from questorharness.commands.types import CommandContext, CommandResult, MemoryCommandBackend


def _handle_memory_edit_command(
    args: str,
    context: CommandContext,
    backend: MemoryCommandBackend,
) -> CommandResult:
    memory_dir = backend.get_memory_dir()
    target = backend.get_entrypoint()
    if args.strip():
        path, invalid = _resolve_memory_entry_path(memory_dir, args.strip())
        if invalid:
            return CommandResult(message="Memory entry path must stay within the configured memory directory.")
        if path is None:
            return CommandResult(message=f"Memory entry not found: {args.strip()}")
        target = path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch(exist_ok=True)
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not editor:
        return CommandResult(message=f"Memory file ready: {target}\nSet $VISUAL or $EDITOR to open it from /memory edit.")
    result = subprocess.run([editor, str(target)], cwd=context.cwd, check=False)
    if result.returncode != 0:
        return CommandResult(message=f"Editor exited with status {result.returncode}: {editor}")
    return CommandResult(message=f"Edited memory file: {target}")


def _parse_memory_add_flags(args: str):
    """Parse optional ``/memory add`` type/scope flags."""

    memory_type = DEFAULT_MEMORY_TYPE
    scope = DEFAULT_MEMORY_SCOPE
    rest = args.strip()
    changed = True
    while changed:
        changed = False
        if rest.startswith("--type "):
            _, _, tail = rest.partition(" ")
            raw, _, rest = tail.partition(" ")
            parsed = parse_memory_type(raw, default=DEFAULT_MEMORY_TYPE)
            if parsed is not None:
                memory_type = parsed
            changed = True
        if rest.startswith("--scope "):
            _, _, tail = rest.partition(" ")
            raw, _, rest = tail.partition(" ")
            parsed_scope = parse_memory_scope(raw, default=DEFAULT_MEMORY_SCOPE)
            if parsed_scope is not None:
                scope = parsed_scope
            changed = True
    return memory_type, scope, rest


def _handle_memory_validate_command(context: CommandContext) -> CommandResult:
    memory_dir = get_project_memory_dir(context.cwd)
    headers = scan_memory_files(context.cwd, max_files=500)
    issues: list[str] = []
    for header in headers:
        raw_type = header.frontmatter.get("type") or header.frontmatter.get("memory_type")
        if parse_memory_type(raw_type) is None:
            issues.append(
                f"- {header.relative_path}: invalid or missing type {raw_type!r}; expected {', '.join(MEMORY_TYPES)}"
            )
        if "team" in Path(header.relative_path).parts:
            try:
                text = header.path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            secret_error = check_team_memory_secrets(text)
            if secret_error:
                issues.append(f"- {header.relative_path}: {secret_error}")
    if not issues:
        return CommandResult(
            message=(
                "Memory validation passed.\n"
                f"- files: {len(headers)}\n"
                f"- memory_dir: {memory_dir}"
            )
        )
    return CommandResult(message="Memory validation issues:\n" + "\n".join(issues))


def _handle_memory_session_command(args: str, context: CommandContext) -> CommandResult:
    action = args.split(maxsplit=1)[0] if args.strip() else "status"
    path = get_session_memory_path(context.cwd, context.session_id or "default")
    if action == "update":
        path = update_session_memory_file(
            context.cwd,
            context.engine.messages,
            tool_metadata=context.engine.tool_metadata,
            session_id=context.session_id or "default",
        )
        return CommandResult(message=f"Updated session memory: {path}")
    if action == "show":
        content = get_session_memory_content(path)
        return CommandResult(message=content or f"No session memory at {path}")
    return CommandResult(
        message=(
            "Session memory:\n"
            f"- path: {path}\n"
            f"- exists: {path.exists()}\n"
            "Commands: /memory session [status|show|update]"
        )
    )


def _handle_memory_team_command(args: str, context: CommandContext) -> CommandResult:
    action = args.split(maxsplit=1)[0] if args.strip() else "status"
    team_dir = ensure_team_memory_vault(context.cwd)
    if action == "list":
        files = sorted(path for path in team_dir.rglob("*.md") if path.name != "MEMORY.md")
        return CommandResult(message="\n".join(str(path.relative_to(team_dir)) for path in files) or "No team memory files.")
    if action == "validate":
        issues: list[str] = []
        for path in sorted(team_dir.rglob("*.md")):
            if path.name == "MEMORY.md":
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            secret_error = check_team_memory_secrets(text)
            if secret_error:
                issues.append(f"- {path.relative_to(team_dir)}: {secret_error}")
        return CommandResult(message="Team memory validation passed." if not issues else "\n".join(issues))
    return CommandResult(
        message=(
            "Team memory:\n"
            f"- directory: {get_team_memory_dir(context.cwd)}\n"
            f"- exists: {team_dir.exists()}\n"
            "Commands: /memory team [status|list|validate]"
        )
    )


def _handle_memory_agent_command(args: str, context: CommandContext) -> CommandResult:
    parts = args.split()
    action = parts[0] if parts else "status"
    agent_type = parts[1] if len(parts) > 1 else "default"
    scope = parts[2] if len(parts) > 2 else "project"
    if scope not in {"user", "project", "local"}:
        return CommandResult(message="Agent memory scope must be one of: user, project, local")
    if action == "snapshot":
        target = initialize_agent_memory_from_snapshot(context.cwd, agent_type, scope)  # type: ignore[arg-type]
        return CommandResult(message=f"Initialized agent memory from snapshot: {target}" if target else "No snapshot found.")
    vault = ensure_agent_memory_vault(context.cwd, agent_type, scope)  # type: ignore[arg-type]
    return CommandResult(
        message=(
            "Agent memory:\n"
            f"- agent_type: {agent_type}\n"
            f"- scope: {scope}\n"
            f"- directory: {vault}\n"
            f"- entrypoint: {get_agent_memory_entrypoint(context.cwd, agent_type, scope)}"
        )
    )


def _resolve_memory_entry_path(memory_dir: Path, candidate: str) -> tuple[Path | None, bool]:
    """Resolve a memory entry path while enforcing containment under ``memory_dir``."""

    base = memory_dir.resolve()
    resolved, invalid = _resolve_memory_candidate(base, candidate)
    if invalid:
        return None, True
    if resolved is not None and resolved.exists():
        return resolved, False
    fallback, invalid = _resolve_memory_candidate(base, f"{candidate}.md")
    if invalid:
        return None, True
    if fallback is not None and fallback.exists():
        return fallback, False
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", candidate.strip().lower()).strip("_")
    if slug and slug != candidate:
        slugged, invalid = _resolve_memory_candidate(base, f"{slug}.md")
        if invalid:
            return None, True
        if slugged is not None and slugged.exists():
            return slugged, False
    return None, False


def _memory_backend_for_context(context: CommandContext) -> MemoryCommandBackend:
    """Return the active slash-command memory backend for this command context."""

    if context.memory_backend is not None:
        return context.memory_backend
    cwd = context.cwd
    return MemoryCommandBackend(
        label="QuestorHarness project memory",
        default_type="project",
        default_category="knowledge",
        get_memory_dir=lambda: get_project_memory_dir(cwd),
        get_entrypoint=lambda: get_memory_entrypoint(cwd),
        list_files=lambda: list_memory_files(cwd),
        add_entry=lambda title, content: add_memory_entry(cwd, title, content),
        remove_entry=lambda name: remove_memory_entry(cwd, name),
    )


def _resolve_memory_candidate(memory_dir: Path, candidate: str) -> tuple[Path | None, bool]:
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        path = memory_dir / path
    resolved = path.resolve()
    try:
        resolved.relative_to(memory_dir)
    except ValueError:
        return None, True
    return resolved, False

# questor: allow R7 -- until W8 adds the mirror test
