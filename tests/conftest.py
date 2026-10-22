"""Shared test fixtures."""

from __future__ import annotations

import sys

import pytest
import pytest_asyncio

from questorharness.tasks.manager import shutdown_task_manager


# Tests whose assumptions are POSIX-only (bash syntax, fcntl, ps output,
# symlink privileges, interactive Windows console). The project itself keeps
# its native-Windows shell support; these tests are skipped on Windows so the
# baseline reflects real failures instead of platform mismatches.
_WINDOWS_ENVIRONMENT_SKIPS = {
    "tests/test_autopilot/test_verification.py::test_run_verification_end_to_end_without_shell": (
        "argv parsing assumes a POSIX-style executable path without spaces"
    ),
    "tests/test_bridge/test_session_flow.py::test_bridge_session_writes_output_in_cwd": (
        "session command uses POSIX printf through a native Windows shell"
    ),
    "tests/test_hooks/test_executor.py::test_command_hook_executes": (
        "hook command uses POSIX printf, unavailable in the native Windows shell"
    ),
    "tests/test_hooks/test_priority.py::test_executor_runs_hooks_in_priority_order": (
        "hook commands use POSIX printf, unavailable in the native Windows shell"
    ),
    "tests/test_questor/test_gateway.py::test_stop_gateway_process_kills_matching_workspace_processes": (
        "gateway process discovery parses POSIX ps output"
    ),
    "tests/test_sandbox/test_path_validator.py::test_symlink_escape_blocked": (
        "creating symlinks requires Windows Developer Mode or administrator rights"
    ),
    "tests/test_swarm/test_lockfile.py::test_exclusive_file_lock_creates_lock_file_on_posix": (
        "POSIX fcntl is unavailable on Windows"
    ),
    "tests/test_swarm/test_registry.py::test_registry_registers_subprocess_and_in_process": (
        "in-process swarm backend is disabled when swarm mailbox capability is unavailable"
    ),
    "tests/test_swarm/test_registry.py::test_get_executor_in_process": (
        "in-process swarm backend is disabled when swarm mailbox capability is unavailable"
    ),
    "tests/test_tasks/test_manager.py::test_create_shell_task_and_read_output": (
        "shell task uses POSIX shell syntax on native Windows"
    ),
    "tests/test_tasks/test_manager.py::test_create_agent_task_with_command_override_and_write": (
        "shell task uses POSIX while/read syntax on native Windows"
    ),
    "tests/test_tasks/test_manager.py::test_write_to_stopped_agent_task_restarts_process": (
        "shell task uses POSIX while/read syntax on native Windows"
    ),
    "tests/test_tasks/test_manager.py::test_start_process_forwards_env_to_subprocess": (
        "shell task uses POSIX printf syntax on native Windows"
    ),
    "tests/test_tasks/test_manager.py::test_completion_listener_fires_when_task_finishes": (
        "shell task uses POSIX shell syntax on native Windows"
    ),
    "tests/test_tools/test_core_tools.py::test_bash_tool_runs_command": (
        "bash tool test uses POSIX printf on native Windows"
    ),
    "tests/test_tools/test_core_tools.py::test_cron_and_remote_trigger_tools": (
        "trigger command uses POSIX printf on native Windows"
    ),
    "tests/test_ui/test_modes.py::test_input_session_updates_prompt_modes": (
        "prompt_toolkit requires an interactive Windows console"
    ),
    "tests/test_utils/test_shell.py::test_create_shell_subprocess_defaults_stdin_to_devnull": (
        "test assumes bash, but native Windows resolves to cmd.exe or PowerShell"
    ),
}


def pytest_collection_modifyitems(config, items):
    if sys.platform != "win32":
        return
    for item in items:
        reason = _WINDOWS_ENVIRONMENT_SKIPS.get(item.nodeid)
        if reason:
            item.add_marker(pytest.mark.skip(reason=reason))


@pytest_asyncio.fixture(autouse=True)
async def _reset_background_task_manager():
    yield
    await shutdown_task_manager()
