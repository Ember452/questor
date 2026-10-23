from pathlib import Path

from questorharness.config.settings import Settings
from questorharness.capabilities.memory import add_memory_entry as add_project_memory_entry
from questorharness.capabilities.context.prompts import build_runtime_system_prompt

from questor.memory import add_memory_entry as add_questor_memory_entry
from questor.memory import list_memory_files as list_questor_memory_files
from questor.memory import remove_memory_entry as remove_questor_memory_entry
from questor.prompts import build_questor_system_prompt
from questor.workspace import (
    get_bootstrap_path,
    get_identity_path,
    get_soul_path,
    get_user_path,
    initialize_workspace,
)


def test_questor_prompt_includes_persona_and_memory(tmp_path: Path):
    workspace = tmp_path / ".questor-home"
    initialize_workspace(workspace)
    get_soul_path(workspace).write_text("# soul\nSpeak like a calm operator.\n", encoding="utf-8")
    get_identity_path(workspace).write_text("# identity\nName: questor\n", encoding="utf-8")
    get_user_path(workspace).write_text("# user\nPrefers terse answers.\n", encoding="utf-8")
    get_bootstrap_path(workspace).write_text("# bootstrap\nAsk a few high-value questions.\n", encoding="utf-8")
    add_questor_memory_entry(workspace, "timezone", "The user prefers UTC timestamps.")

    prompt = build_questor_system_prompt(tmp_path, workspace=workspace)

    assert "You are QuestorHarness" in prompt
    assert "Speak like a calm operator." in prompt
    assert "Name: questor" in prompt
    assert "Prefers terse answers." in prompt
    assert "Ask a few high-value questions." in prompt
    assert "timezone.md" in prompt
    assert "UTC timestamps" in prompt


def test_questor_runtime_prompt_can_exclude_project_memory(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_COORDINATOR_MODE", raising=False)
    monkeypatch.setenv("QUESTORHARNESS_DATA_DIR", str(tmp_path / "data"))
    workspace = tmp_path / ".questor-home"
    initialize_workspace(workspace)
    add_questor_memory_entry(workspace, "personal", "questor-only personal fact")
    add_project_memory_entry(tmp_path, "project", "project memory should not leak")

    base_prompt = build_questor_system_prompt(tmp_path, workspace=workspace)
    runtime_prompt = build_runtime_system_prompt(
        Settings(system_prompt=base_prompt),
        cwd=tmp_path,
        latest_user_prompt="hello",
        include_project_memory=False,
    )

    assert "questor-only personal fact" in runtime_prompt
    assert "project memory should not leak" not in runtime_prompt


def test_questor_memory_uses_schema_and_soft_delete(tmp_path: Path):
    workspace = tmp_path / ".questor-home"
    initialize_workspace(workspace)

    path = add_questor_memory_entry(workspace, "timezone", "The user prefers UTC timestamps.")

    text = path.read_text(encoding="utf-8")
    assert "schema_version: 1" in text
    assert "type: \"personal\"" in text

    assert remove_questor_memory_entry(workspace, "timezone") is True
    assert path.exists()
    assert list_questor_memory_files(workspace) == []
    assert "disabled: true" in path.read_text(encoding="utf-8")
