#!/usr/bin/env python3
"""One extraction layer for the seven namespaces (R10).

Both the generator (`gen_namespaces.py`) and the guard
(`check_name_registries.py`) call this module, so the document can never be
derived from a different reading of the code than the check that validates it.

Each extractor returns ``(name, producer_path)`` pairs with a repo-relative
posix producer. Dynamic names (a tool whose ``name`` is set in ``__init__``)
fall back to the class name so they still have to be registered.
"""

from __future__ import annotations

import ast
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

try:
    from ._guard_kit import read_text, tracked_files
except ImportError:  # direct script execution
    from _guard_kit import read_text, tracked_files  # type: ignore[no-redef]

NAMESPACES = (
    "tool",
    "command",
    "event",
    "config-key",
    "env",
    "entry-point",
    "skill-id",
)

ENV_RE = re.compile(r"[\"'](QUESTORHARNESS_[A-Z0-9_]+)[\"']")
EVENT_FILES = (
    "src/questorharness/contracts/domain/events.py",
    "src/questorharness/surfaces/channels/bus/events.py",
)
TOOL_PACKAGE = "src/questorharness/capabilities/tools"
SETTINGS_MODULE = "src/questorharness/config/settings_models.py"


def _tool_names(root: Path) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for path in tracked_files(root, ("src",)):
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(read_text(path))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {getattr(base, "id", getattr(base, "attr", "")) for base in node.bases}
            if "BaseTool" not in bases:
                continue
            declared = ""
            for statement in node.body:
                if isinstance(statement, ast.Assign) and any(
                    getattr(target, "id", None) == "name" for target in statement.targets
                ):
                    value = statement.value
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        declared = value.value
            found.append((declared or node.name, relative))
    return sorted(found)


def _command_names(root: Path) -> list[tuple[str, str]]:
    from inspect import getsourcefile
    from unittest import mock

    from questorharness.commands.registry import create_default_command_registry

    fallback = "src/questorharness/commands/registry.py"
    # 注册表在注册期会把**用户家目录**里装的技能提升为斜杠命令
    # (families/account.py 的 _register_user_invocable_skill_commands)。
    # 不钉住它,本文档会随开发机安装的技能漂移——CI 上家目录干净,渲染
    # 就少一截,--check 永远红。与 prompt_surface 同一个补丁口径:用户技能为零,
    # 只让仓库自带(bundled)的技能与内建命令进文档。
    with mock.patch(
        "questorharness.capabilities.skills.loader.get_user_skill_dirs",
        return_value=[],
    ):
        registry = create_default_command_registry()
    found: list[tuple[str, str]] = []
    for command in registry.list_commands():
        source = getsourcefile(command.handler) or ""
        try:
            relative = Path(source).resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            relative = fallback
        found.append((command.name, relative))
    return sorted(found)


def _event_names(root: Path) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for relative in EVENT_FILES:
        path = root / relative
        if not path.exists():
            continue
        tree = ast.parse(read_text(path))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            names = set()
            for item in node.decorator_list:
                target = item.func if isinstance(item, ast.Call) else item
                names.add(getattr(target, "id", getattr(target, "attr", "")))
            if "dataclass" in names:
                found.append((node.name, relative))
    return sorted(found)


def _config_keys(root: Path) -> list[tuple[str, str]]:
    from questorharness.config.settings_models import Settings

    return sorted((name, SETTINGS_MODULE) for name in Settings.model_fields)


def _env_names(root: Path) -> list[tuple[str, str]]:
    found: dict[str, str] = {}
    for path in tracked_files(root, ("src",)):
        relative = path.relative_to(root).as_posix()
        for match in ENV_RE.finditer(read_text(path)):
            found.setdefault(match.group(1), relative)
    return sorted(found.items())


def _entry_points(root: Path) -> list[tuple[str, str]]:
    data = tomllib.loads(read_text(root / "pyproject.toml"))
    project = data.get("project", {})
    found: list[tuple[str, str]] = []
    for name in project.get("scripts", {}):
        found.append((name, "pyproject.toml"))
    for group, entries in project.get("entry-points", {}).items():
        for name in entries:
            found.append((f"{group}:{name}", "pyproject.toml"))
    return sorted(found)


def _skill_ids(root: Path) -> list[tuple[str, str]]:
    from questorharness.capabilities.skills.bundled import get_bundled_skills

    producer = "src/questorharness/capabilities/skills/bundled/__init__.py"
    return sorted((skill.name, producer) for skill in get_bundled_skills())


EXTRACTORS = {
    "tool": _tool_names,
    "command": _command_names,
    "event": _event_names,
    "config-key": _config_keys,
    "env": _env_names,
    "entry-point": _entry_points,
    "skill-id": _skill_ids,
}

EMPTY_CELL = "—"


@dataclass(frozen=True)
class Row:
    """One registered name. Cells are raw markdown text."""

    namespace: str
    name: str
    producer: str
    consumers: str


def read_rows(path: str | Path) -> dict[str, list[Row]]:
    """Parse the namespace document into ``{namespace: [Row, ...]}`."""
    rows: dict[str, list[Row]] = {namespace: [] for namespace in NAMESPACES}
    namespace = ""
    for line in read_text(path).splitlines():
        if line.startswith("## "):
            namespace = line[3:].strip()
            rows.setdefault(namespace, [])
            continue
        if not line.startswith("| ") or line.startswith("| name") or line.startswith("| ---"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 3 or not namespace:
            continue
        rows[namespace].append(Row(namespace, cells[0], cells[1], cells[2]))
    return rows


def consumer_tokens(cell: str) -> list[str]:
    """Return the repo paths referenced from a consumers cell."""
    return [token.strip() for token in re.findall(r"`([^`]+)`", cell)]


def collect_code_names(root: Path) -> dict[str, list[tuple[str, str]]]:
    """Return ``{namespace: [(name, producer), ...]}`` for all seven namespaces."""
    return {namespace: EXTRACTORS[namespace](root) for namespace in NAMESPACES}
