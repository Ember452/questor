"""P2 arg-key 词典与抽取器（design/03 §11；T5）。"""

from __future__ import annotations

from questor.contracts.tool_args import (
    ACTION_ARG_KEYS,
    NULL_SINKS,
    PATCH_PATH_PREFIXES,
    PATH_ARG_KEYS,
    PROTECTED_IN_ROOTS,
    SHELL_ARG_KEYS,
)
from questor.kernel.tool_arguments import extract_actions, extract_paths, extract_shell_commands


def test_arg_dictionaries_are_complete_and_protected_roots_are_named() -> None:
    assert "file_path" in PATH_ARG_KEYS
    assert "command" in SHELL_ARG_KEYS
    assert "action" in ACTION_ARG_KEYS
    assert "*** Add File: " in PATCH_PATH_PREFIXES
    assert "/dev/null" in NULL_SINKS
    assert {"mcp.json", "config.json", ".env"} <= PROTECTED_IN_ROOTS


def test_extract_paths_includes_scalar_list_and_patch_headers() -> None:
    paths = extract_paths(
        {
            "file_path": "a.txt",
            "paths": ["b.txt", "c.txt"],
            "patch": "*** Add File: new.py\n*** Update File: old.py\ncontent",
            "unexpected": 1,
        }
    )
    assert paths == ("a.txt", "b.txt", "c.txt", "new.py", "old.py")


def test_extract_shell_commands_accepts_string_and_list_without_joining_secrets() -> None:
    assert extract_shell_commands({"command": "ls"}) == ("ls",)
    assert extract_shell_commands({"commands": ["pwd", "id"]}) == ("pwd", "id")
    assert extract_shell_commands({"script": 20}) == ()


def test_extract_actions_and_invalid_shapes_are_ignored() -> None:
    assert extract_actions({"action": "write"}) == ("write",)
    assert extract_paths({"file_path": {"nested": "x"}}) == ()
    assert extract_paths(None) == ()
