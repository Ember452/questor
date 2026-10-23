#!/usr/bin/env python3
"""Keep the "add a tool" radius at one file (plan 01, W5).

Three assertions:

1. every ``BaseTool`` subclass carries an explicit ``capabilities =
   ToolCapabilities(...)`` line — a class-level default cannot distinguish
   "declared False" from "forgot to declare";
2. the four former shared lists (compaction, coordinator, swarm permissions,
   carry-over) no longer hold tool names: no list/set literal with two or more
   tool names, and no ``== "<tool name>"`` comparison;
3. discovery and the explicit registration order agree, so a tool cannot be
   silently dropped by an import error.

The two policy lists in ``coordinator.py`` (which tools a worker may use) are
named exceptions: they are a scoped decision about worker capability, not a
per-tool fact, and a new tool is not added to them by default.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Sequence
from pathlib import Path

try:
    from ._guard_kit import EXIT_CONFIG, EXIT_OK, EXIT_RED, read_text, run_self_test, tracked_files
except ImportError:  # direct script execution
    from _guard_kit import EXIT_CONFIG, EXIT_OK, EXIT_RED, read_text, run_self_test, tracked_files

REPO_ROOT = Path(__file__).resolve().parents[2]

# The files that used to be edited whenever a tool was added.
CONSUMERS = (
    "src/questorharness/capabilities/context/compact/constants.py",
    "src/questorharness/capabilities/context/coordinator.py",
    "src/questorharness/runtime/swarm/permission_sync.py",
    "src/questorharness/engine/tool_metadata.py",
)
# Worker capability policy, not per-tool metadata.
POLICY_LISTS = {
    "src/questorharness/capabilities/context/coordinator.py": {"_WORKER_TOOLS", "_SIMPLE_WORKER_TOOLS"},
}

DISCOVERY_MODULE = "questorharness.capabilities.tools.registry"


def _tool_names() -> set[str]:
    from questorharness.capabilities.tools.registry import (
        CONDITIONAL_CLASSES,
        _BUILTIN_CLASSES,
        discover_builtin_tools,
    )

    discovered = discover_builtin_tools()
    names = set()
    for class_name in (*_BUILTIN_CLASSES, *sorted(CONDITIONAL_CLASSES)):
        cls = discovered.get(class_name)
        if cls is None:
            continue
        declared = getattr(cls, "name", "")
        if isinstance(declared, str) and declared:
            names.add(declared)
        else:
            names.add(cls.__name__)
    return names


def _class_bodies(path: Path) -> list[ast.ClassDef]:
    tree = ast.parse(read_text(path))
    found = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and any(
            getattr(base, "id", "") == "BaseTool" for base in node.bases
        ):
            found.append(node)
    return found


def _missing_declarations(root: Path) -> list[str]:
    problems: list[str] = []
    for path in tracked_files(root, ("src",)):
        for node in _class_bodies(path):
            has = False
            for statement in node.body:
                if isinstance(statement, ast.Assign) and any(
                    getattr(target, "id", None) == "capabilities" for target in statement.targets
                ):
                    has = True
            if not has:
                problems.append(
                    f"{path.relative_to(root).as_posix()}: {node.name} has no capabilities declaration"
                )
    return problems


def _literal_names(node: ast.AST, tool_names: set[str]) -> int:
    count = 0
    for item in ast.walk(node):
        if isinstance(item, ast.Constant) and isinstance(item.value, str) and item.value in tool_names:
            count += 1
    return count


def _consumer_problems(root: Path, tool_names: set[str]) -> list[str]:
    problems: list[str] = []
    for relative in CONSUMERS:
        path = root / relative
        if not path.exists():
            problems.append(f"{relative}: consumer file is missing")
            continue
        tree = ast.parse(read_text(path))
        allowed = POLICY_LISTS.get(relative, set())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                targets = {getattr(target, "id", None) for target in node.targets}
                if targets & allowed:
                    continue
                value = node.value
                if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
                    found = _literal_names(value, tool_names)
                    if found >= 2:
                        problems.append(
                            f"{relative}:{node.lineno}: local list of {found} tool names (declare it on the tool)"
                        )
            if isinstance(node, ast.Compare):
                # Only ``tool_name == "<name>"`` counts: a category comparison
                # (``category == "skill"``) is not a tool-name list.
                left = node.left
                if not (isinstance(left, ast.Name) and left.id == "tool_name"):
                    continue
                if len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq):
                    right = node.comparators[0]
                    if isinstance(right, ast.Constant) and right.value in tool_names:
                        problems.append(
                            f"{relative}:{node.lineno}: compares against the tool name '{right.value}'"
                        )
    return problems


def _discovery_problems() -> list[str]:
    from questorharness.capabilities.tools.registry import (
        CONDITIONAL_CLASSES,
        _BUILTIN_CLASSES,
        discover_builtin_tools,
    )

    discovered = discover_builtin_tools()
    expected = len(_BUILTIN_CLASSES) + len(CONDITIONAL_CLASSES)
    if len(discovered) != expected:
        return [f"discovery found {len(discovered)} classes, expected {expected}"]
    return []


def _index_problems() -> list[str]:
    from types import MappingProxyType

    from questorharness.capabilities.tools.registry import capability_index

    index = capability_index()
    if not isinstance(index.by_name, MappingProxyType):
        return ["capability_index().by_name must be immutable (MappingProxyType)"]
    return []


def collect() -> list[str]:
    """Collect every radius problem. Imported lazily so the CLI can report config errors."""
    problems = _missing_declarations(REPO_ROOT)
    problems.extend(_consumer_problems(REPO_ROOT, _tool_names()))
    problems.extend(_discovery_problems())
    problems.extend(_index_problems())
    return problems


def _self_test() -> int:
    import tempfile

    cases: list[tuple[str, bool, str]] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "src").mkdir()
        modules = {
            "src/pkg/__init__.py": "",
            "src/pkg/tools.py": (
                "from a import BaseTool\n"
                "class GoodTool(BaseTool):\n"
                "    name = 'good'\n"
                "    capabilities = 1\n"
                "class BadTool(BaseTool):\n"
                "    name = 'bad'\n"
            ),
        }
        for relative, text in modules.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        import subprocess

        subprocess.run(["git", "init", "-q"], cwd=root, check=False)
        subprocess.run(["git", "add", "-A"], cwd=root, check=False)
        missing = _missing_declarations(root)
        cases.append(
            (
                "missing-declaration",
                any("BadTool" in item for item in missing) and not any("GoodTool" in item for item in missing),
                f"{missing}",
            )
        )

        for relative in CONSUMERS:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("VALUE = 1\n", encoding="utf-8")
        probe = root / CONSUMERS[0]
        probe.write_text(
            'NAMES = ["good", "bad"]\nif tool_name == "good":\n    pass\n', encoding="utf-8"
        )
        problems = _consumer_problems(root, {"good", "bad"})
        cases.append(
            (
                "consumer-list-and-compare",
                len(problems) == 2,
                f"{problems}",
            )
        )
    return run_self_test(cases)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="prove the radius checks can go red")
    parser.add_argument(
        "--fail-on-empty",
        action="store_true",
        help="treat an empty declaration scan as a configuration error",
    )
    args = parser.parse_args(argv)
    if args.self_test:
        return _self_test()

    try:
        tools = _tool_names()
    except Exception as exc:  # noqa: BLE001 - the registry may fail to import
        print(f"tool radius: config error: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    if args.fail_on_empty and not tools:
        print("tool radius: config error: no tools discovered", file=sys.stderr)
        return EXIT_CONFIG

    problems = collect()
    if problems:
        print("tool radius: shared points found:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return EXIT_RED

    from questorharness.capabilities.tools.registry import capability_index

    index = capability_index()
    print(
        f"tool radius: OK ({len(tools)} tools declared, {len(index.read_only_tools)} read-only, "
        f"{len(index.compactable_tools)} compactable, {len(CONSUMERS)} former shared files clean)"
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
