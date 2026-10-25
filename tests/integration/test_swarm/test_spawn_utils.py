"""Tests for teammate spawn helper behavior."""

from __future__ import annotations

import sys

from questorharness.runtime.swarm.spawn_utils import (
    TEAMMATE_COMMAND_ENV_VAR,
    build_inherited_cli_flags,
    build_inherited_env_vars,
    get_teammate_command,
)


def test_get_teammate_command_prefers_current_interpreter(monkeypatch):
    monkeypatch.delenv(TEAMMATE_COMMAND_ENV_VAR, raising=False)
    monkeypatch.setattr(sys, "executable", "/tmp/current-python")

    command = get_teammate_command()

    assert command == "/tmp/current-python"


def test_build_inherited_cli_flags_forwards_tool_surface() -> None:
    """子代理的工具白/黑名单必须下发给子进程（否则声明静默失效）。"""
    flags = build_inherited_cli_flags(
        allowed_tools=["read_file", "grep"],
        disallowed_tools=["write_file", "edit_file"],
    )
    assert flags[flags.index("--allowed-tools") + 1] == "read_file,grep"
    assert flags[flags.index("--disallowed-tools") + 1] == "write_file,edit_file"


def test_build_inherited_cli_flags_omits_empty_tool_surface() -> None:
    """未声明工具面时不得凭空造 flag（否则会把“继承全部”误降为“全部禁用”）。"""
    flags = build_inherited_cli_flags()
    assert "--allowed-tools" not in flags
    assert "--disallowed-tools" not in flags


def test_build_inherited_env_vars_disables_coordinator_mode(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_COORDINATOR_MODE", "1")

    env = build_inherited_env_vars()

    assert env["CLAUDE_CODE_COORDINATOR_MODE"] == "0"


def test_build_inherited_env_vars_forwards_questorharness_config_dir(monkeypatch):
    monkeypatch.setenv("QUESTORHARNESS_CONFIG_DIR", "/opt/data/.questorharness")

    env = build_inherited_env_vars()

    assert env["QUESTORHARNESS_CONFIG_DIR"] == "/opt/data/.questorharness"


def test_build_inherited_env_vars_includes_questorharness_auth_vars(monkeypatch):
    monkeypatch.setenv("QUESTORHARNESS_PROVIDER", "openai")
    monkeypatch.setenv("QUESTORHARNESS_BASE_URL", "https://relay.example.com/v1")
    monkeypatch.setenv("QUESTORHARNESS_OPENAI_API_KEY", "sk-oh-openai")
    monkeypatch.setenv("QUESTORHARNESS_ANTHROPIC_API_KEY", "sk-oh-anthropic")

    env = build_inherited_env_vars()

    assert env["QUESTORHARNESS_AGENT_TEAMS"] == "1"
    assert env["QUESTORHARNESS_PROVIDER"] == "openai"
    assert env["QUESTORHARNESS_BASE_URL"] == "https://relay.example.com/v1"
    assert env["QUESTORHARNESS_OPENAI_API_KEY"] == "sk-oh-openai"
    assert env["QUESTORHARNESS_ANTHROPIC_API_KEY"] == "sk-oh-anthropic"


# ---------------------------------------------------------------------------
# build_inherited_cli_flags – model handling
# ---------------------------------------------------------------------------


def test_build_inherited_cli_flags_explicit_model_included():
    flags = build_inherited_cli_flags(model="claude-opus-4-5")
    assert "--model" in flags
    idx = flags.index("--model")
    assert "claude-opus-4-5" in flags[idx + 1]


def test_build_inherited_cli_flags_inherit_model_excluded():
    """model='inherit' must NOT produce a --model flag so the subprocess
    picks up the parent's model from the QUESTORHARNESS_MODEL env var."""
    flags = build_inherited_cli_flags(model="inherit")
    assert "--model" not in flags


def test_build_inherited_cli_flags_none_model_excluded():
    flags = build_inherited_cli_flags(model=None)
    assert "--model" not in flags


def test_build_inherited_cli_flags_empty_string_model_excluded():
    flags = build_inherited_cli_flags(model="")
    assert "--model" not in flags


def test_build_inherited_cli_flags_forwards_system_prompt_as_replace():
    flags = build_inherited_cli_flags(system_prompt="You are a specialized worker.")

    assert "--system-prompt" in flags
    idx = flags.index("--system-prompt")
    assert "specialized worker" in flags[idx + 1]
    assert "--append-system-prompt" not in flags


def test_build_inherited_cli_flags_forwards_system_prompt_as_append():
    flags = build_inherited_cli_flags(
        system_prompt="Extra worker instructions.",
        system_prompt_mode="append",
    )

    assert "--append-system-prompt" in flags
    idx = flags.index("--append-system-prompt")
    assert "Extra worker instructions." in flags[idx + 1]
    assert "--system-prompt" not in flags
