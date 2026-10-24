"""Runtime helpers for questor."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from questor.memory import create_memory_command_backend
from questor.prompts import build_questor_system_prompt
from questor.session_storage import QuestorSessionBackend
from questor.workspace import (
    get_memory_dir,
    get_plugins_dir,
    get_sessions_dir,
    get_skills_dir,
    initialize_workspace,
)
from questorharness.api import (
    AssistantTextDelta,
    AssistantTurnComplete,
    CompactProgressEvent,
    ErrorEvent,
    StatusEvent,
    SupportsStreamingMessages,
    build_runtime,
    close_runtime,
    handle_line,
    run_terminal_repl,
    start_runtime,
)


def _questor_extra_roots(workspace: str | Path | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    root = initialize_workspace(workspace)
    return ((str(get_skills_dir(root)),), (str(get_plugins_dir(root)),))


async def run_questor_backend(
    *,
    cwd: str | None = None,
    workspace: str | Path | None = None,
    model: str | None = None,
    max_turns: int | None = None,
    provider_profile: str | None = None,
    api_client: SupportsStreamingMessages | None = None,
    restore_messages: list[dict] | None = None,
    restore_tool_metadata: dict[str, object] | None = None,
    backend_only: bool = True,
) -> int:
    """Run the shared React backend host with questor workspace semantics."""
    del backend_only
    cwd_path = str(Path(cwd or Path.cwd()).resolve())
    workspace_root = initialize_workspace(workspace)
    extra_skill_dirs, extra_plugin_roots = _questor_extra_roots(workspace_root)
    return await run_terminal_repl(
        cwd=cwd_path,
        model=model,
        max_turns=max_turns,
        system_prompt=build_questor_system_prompt(cwd_path, workspace=workspace_root),
        api_client=api_client,
        restore_messages=restore_messages,
        restore_tool_metadata=restore_tool_metadata,
        overrides={
            "active_profile": provider_profile,
            "session_backend": QuestorSessionBackend(workspace_root),
            "extra_skill_dirs": extra_skill_dirs,
            "extra_plugin_roots": extra_plugin_roots,
            "memory_backend": create_memory_command_backend(workspace_root),
            "include_project_memory": False,
            "autodream_context": {
                "memory_dir": str(get_memory_dir(workspace_root)),
                "session_dir": str(get_sessions_dir(workspace_root)),
                "app_label": "questor personal memory",
                "runner_module": "questor",
            },
        },
    )


async def run_questor_print_mode(
    *,
    prompt: str,
    cwd: str | None = None,
    workspace: str | Path | None = None,
    model: str | None = None,
    max_turns: int | None = None,
    provider_profile: str | None = None,
) -> int:
    """Run a single questor prompt and print the assistant output."""
    cwd_path = str(Path(cwd or Path.cwd()).resolve())
    workspace_root = initialize_workspace(workspace)
    extra_skill_dirs, extra_plugin_roots = _questor_extra_roots(workspace_root)
    previous_cwd = Path.cwd()
    os.chdir(cwd_path)
    try:
        bundle = await build_runtime(
            model=model,
            max_turns=max_turns,
            system_prompt=build_questor_system_prompt(cwd_path, workspace=workspace_root),
            active_profile=provider_profile,
            session_backend=QuestorSessionBackend(workspace_root),
            enforce_max_turns=max_turns is not None,
            extra_skill_dirs=extra_skill_dirs,
            extra_plugin_roots=extra_plugin_roots,
            memory_backend=create_memory_command_backend(workspace_root),
            include_project_memory=False,
            autodream_context={
                "memory_dir": str(get_memory_dir(workspace_root)),
                "session_dir": str(get_sessions_dir(workspace_root)),
                "app_label": "questor personal memory",
                "runner_module": "questor",
            },
        )
        await start_runtime(bundle)

        async def _print_system(message: str) -> None:
            print(message, file=sys.stderr)

        saw_error = False

        async def _render_event(event) -> None:
            nonlocal saw_error
            if isinstance(event, AssistantTextDelta):
                sys.stdout.write(event.text)
                sys.stdout.flush()
            elif isinstance(event, AssistantTurnComplete):
                sys.stdout.write("\n")
                sys.stdout.flush()
            elif isinstance(event, ErrorEvent):
                saw_error = True
                print(event.message, file=sys.stderr)
            elif isinstance(event, CompactProgressEvent):
                if event.message:
                    print(event.message, file=sys.stderr)
            elif isinstance(event, StatusEvent):
                print(event.message, file=sys.stderr)

        async def _clear_output() -> None:
            return None

        await handle_line(
            bundle,
            prompt,
            print_system=_print_system,
            render_event=_render_event,
            clear_output=_clear_output,
        )
        await close_runtime(bundle)
        return 1 if saw_error else 0
    finally:
        os.chdir(previous_cwd)


# questor: allow R7 -- until W8 adds the mirror test
