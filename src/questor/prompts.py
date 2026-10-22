"""Prompt assembly for questor persona and workspace context."""

from __future__ import annotations

from pathlib import Path

from questorharness.memory import load_memory_prompt as load_project_memory_prompt
from questorharness.prompts.system_prompt import get_base_system_prompt

from questor.memory import load_memory_prompt as load_questor_memory_prompt
from questor.workspace import (
    get_bootstrap_path,
    get_identity_path,
    get_soul_path,
    get_user_path,
    get_workspace_root,
)


def _read_text(path: Path) -> str | None:
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8", errors="replace").strip()
    return content or None


def build_questor_system_prompt(
    cwd: str | Path,
    *,
    workspace: str | Path | None = None,
    extra_prompt: str | None = None,
    include_project_memory: bool = False,
) -> str:
    """Build the custom base prompt for questor sessions."""
    root = get_workspace_root(workspace)
    sections = [get_base_system_prompt()]

    if extra_prompt:
        sections.extend(["# Additional Instructions", extra_prompt.strip()])

    soul = _read_text(get_soul_path(root))
    if soul:
        sections.extend(["# questor Soul", soul])

    identity = _read_text(get_identity_path(root))
    if identity:
        sections.extend(["# questor Identity", identity])

    user = _read_text(get_user_path(root))
    if user:
        sections.extend(["# User Profile", user])

    bootstrap = _read_text(get_bootstrap_path(root))
    if bootstrap:
        sections.extend(["# First-Run Bootstrap", bootstrap])

    sections.extend(
        [
            "# questor Workspace",
            f"- Personal workspace root: {root}",
            "- Personal memory and sessions live under the shared questor workspace root.",
            "- Resume only within questor sessions; do not assume interoperability with plain QuestorHarness sessions.",
        ]
    )

    if questor_memory := load_questor_memory_prompt(root):
        sections.append(questor_memory)

    if include_project_memory:
        project_memory = load_project_memory_prompt(cwd)
        if project_memory:
            sections.append(project_memory)

    return "\n\n".join(section for section in sections if section and section.strip())
