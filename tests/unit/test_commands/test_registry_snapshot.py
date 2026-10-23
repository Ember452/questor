"""Characterization tests for the default command registry.

These pin the two things a family split must not change: the exact help
text, and the canonical command registration order. Aliases are checked
separately because they share the same SlashCommand instance.
"""

from __future__ import annotations

import os
from pathlib import Path

from questorharness.commands.registry import create_default_command_registry

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "commands"


class _EmptySkills:
    def list_skills(self) -> list[object]:
        return []

    def get(self, name: str) -> None:
        del name
        return None


def _build_default(monkeypatch, tmp_path: Path):
    for key in list(os.environ):
        if key.startswith("QUESTORHARNESS_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("QUESTORHARNESS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "questorharness.commands.registry.load_skill_registry",
        lambda *args, **kwargs: _EmptySkills(),
    )
    return create_default_command_registry(plugin_commands=[])


def test_help_text_snapshot(monkeypatch, tmp_path: Path) -> None:
    registry = _build_default(monkeypatch, tmp_path)
    expected = (FIXTURES / "help.txt").read_text(encoding="utf-8")

    assert registry.help_text() + "\n" == expected


def test_command_order_snapshot(monkeypatch, tmp_path: Path) -> None:
    registry = _build_default(monkeypatch, tmp_path)
    expected = [
        line.strip()
        for line in (FIXTURES / "order.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert [command.name for command in registry.list_commands()] == expected


def test_alias_shares_the_canonical_command(monkeypatch, tmp_path: Path) -> None:
    registry = _build_default(monkeypatch, tmp_path)

    exit_command, _ = registry.lookup("/exit")
    quit_command, _ = registry.lookup("/quit")

    assert exit_command.name == "exit"
    assert quit_command is exit_command
