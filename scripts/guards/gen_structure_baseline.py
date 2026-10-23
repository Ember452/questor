#!/usr/bin/env python3
"""Record and verify the structure baseline (plan 01 section 1).

Seventeen metrics pin the shape of the repository so every later wave can be
judged against a machine-readable file instead of prose. Collection always goes
through ``git ls-files`` so untracked scratch output (``__pycache__``,
``.tmp-baseline``) can never move the numbers.

Usage:
    uv run python scripts/guards/gen_structure_baseline.py --check
    uv run python scripts/guards/gen_structure_baseline.py --write
    uv run python scripts/guards/gen_structure_baseline.py --refresh-baseline --reason "..."

``--refresh-baseline`` is deliberately absent from every CI and pre-commit
configuration: refreshing a baseline is a reviewed, human decision, not
something a pipeline may do on its own.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

try:
    from ._guard_kit import (
        EXIT_CONFIG,
        EXIT_OK,
        EXIT_RED,
        GuardConfigError,
        count_lines,
        read_text,
    )
except ImportError:  # direct script execution
    from _guard_kit import (
        EXIT_CONFIG,
        EXIT_OK,
        EXIT_RED,
        GuardConfigError,
        count_lines,
        read_text,
    )

REPO_ROOT = Path(__file__).resolve().parents[2]
TARGET = REPO_ROOT / "tests/fixtures/baseline/structure.json"

BANNED_NAMES = frozenset(
    {
        "utils.py",
        "helpers.py",
        "common.py",
        "base.py",
        "manager.py",
        "service.py",
        "handler.py",
        "processor.py",
        "misc.py",
        "core.py",
        "types.py",
        "constants.py",
    }
)

# B9: the shared files a new tool has to touch today. ``registry.py`` is the
# registration point; the other four keep their own tool-name allow-lists.
TOOL_RADIUS_FILES = (
    "src/questorharness/capabilities/tools/registry.py",
    "src/questorharness/capabilities/context/compact/constants.py",
    "src/questorharness/capabilities/context/coordinator.py",
    "src/questorharness/runtime/swarm/permission_sync.py",
    "src/questorharness/engine/tool_metadata.py",
)

# B15/B16: the package maps that must exist next to the code.
PACKAGE_MAP_DIRS = (
    "src/questorharness/bootstrap",
    "src/questorharness/capabilities",
    "src/questorharness/commands",
    "src/questorharness/config",
    "src/questorharness/contracts",
    "src/questorharness/engine",
    "src/questorharness/providers",
    "src/questorharness/runtime",
    "src/questorharness/surfaces",
)

LONG_BANDS = ((1500, "over_limit"), (1000, "over_soft_limit"), (800, "warning_band"))

# B13: the guards that existed at the baseline. ``gen_*`` scripts are generators,
# not guards, so adding one never moves this number.
BASELINE_GUARDS = (
    "_guard_kit",
    "check_doc_cross_refs",
    "check_layout",
    "check_secret_projection",
    "check_thread_leak",
)


def _git(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise GuardConfigError(f"git {' '.join(args)} failed: {result.stderr.strip()[:200]}")
    return [line for line in result.stdout.splitlines() if line.strip()]


def _tracked(*patterns: str) -> list[str]:
    return _git("ls-files", *patterns)


def _module_name(relative: str) -> str:
    parts = Path(relative).with_suffix("").parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _package_name(relative: str) -> str:
    """Return the two-level package name for a tracked path, or '' for ``src/__init__.py``."""
    parts = Path(relative).with_suffix("").parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts[:2])


def _dotted_package(dotted: str) -> str:
    return ".".join(dotted.split(".")[:2])


def _literal_exports(tree: ast.Module) -> list[str] | None:
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        targets = [target for target in node.targets if getattr(target, "id", None) == "__all__"]
        if not targets:
            continue
        if isinstance(node.value, (ast.List, ast.Tuple)):
            return [item.value for item in node.value.elts if isinstance(item, ast.Constant)]
        return None
    return None


def _imports_of(path: Path, module: str) -> Iterable[str]:
    """Yield absolute dotted targets of every import statement, relative ones resolved."""
    is_package = path.name == "__init__.py"
    package_parts = module.split(".") if is_package else module.split(".")[:-1]
    tree = ast.parse(read_text(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package_parts
                if node.level > 1:
                    base = package_parts[: len(package_parts) - (node.level - 1)]
                parts = [*base]
                if node.module:
                    parts.extend(node.module.split("."))
                yield ".".join(parts)
            elif node.module:
                yield node.module


def _strongly_connected(nodes: Iterable[str], edges: dict[str, set[str]]) -> list[list[str]]:
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    result: list[list[str]] = []
    counter = [0]

    def visit(node: str) -> None:
        index[node] = low[node] = counter[0]
        counter[0] += 1
        stack.append(node)
        on_stack.add(node)
        for neighbour in sorted(edges.get(node, ())):
            if neighbour not in index:
                visit(neighbour)
                low[node] = min(low[node], low[neighbour])
            elif neighbour in on_stack:
                low[node] = min(low[node], index[neighbour])
        if low[node] == index[node]:
            component: list[str] = []
            while True:
                item = stack.pop()
                on_stack.discard(item)
                component.append(item)
                if item == node:
                    break
            if len(component) > 1:
                result.append(sorted(component))

    for node in sorted(nodes):
        if node not in index:
            visit(node)
    return result


def _tool_classes() -> list[tuple[str, str, str]]:
    """Return (path, class name, declared tool name) for every BaseTool subclass."""
    found: list[tuple[str, str, str]] = []
    for relative in _tracked("src"):
        if not relative.endswith(".py"):
            continue
        tree = ast.parse(read_text(REPO_ROOT / relative))
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
                    if isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str):
                        declared = statement.value.value
            found.append((relative, node.name, declared))
    return found


def _metric(value: object, caliber: str, gate: bool = True, **extra: object) -> dict[str, object]:
    payload: dict[str, object] = {"value": value, "caliber": caliber, "gate": gate}
    payload.update(extra)
    return payload


def collect() -> dict[str, dict[str, object]]:
    """Collect the seventeen baseline metrics from the tracked tree."""
    src = [path for path in _tracked("src") if path.endswith(".py")]
    tests = [path for path in _tracked("tests") if path.endswith(".py")]
    if not src or not tests:
        raise GuardConfigError("empty scan target: src or tests has no tracked python files")

    src_modules = [path for path in src if Path(path).name != "__init__.py"]
    inits = [path for path in src if Path(path).name == "__init__.py"]
    with_logic = [
        path
        for path in inits
        if re.search(r"^\s*(async\s+def|def|class)\s", read_text(REPO_ROOT / path), re.MULTILINE)
    ]

    export_counts: list[tuple[int, str]] = []
    missing_all: list[str] = []
    for path in inits:
        tree = ast.parse(read_text(REPO_ROOT / path))
        exports = _literal_exports(tree)
        if exports is None:
            missing_all.append(path)
        else:
            export_counts.append((len(exports), path))
    heavy = sorted((item for item in export_counts if item[0] > 10), reverse=True)

    top_packages = sorted(
        {path.split("/")[2] for path in src if path.startswith("src/questorharness/") and len(path.split("/")) > 3}
    )
    top_without_all = []
    for package in top_packages:
        init = f"src/questorharness/{package}/__init__.py"
        tree = ast.parse(read_text(REPO_ROOT / init))
        if _literal_exports(tree) is None:
            top_without_all.append(package)

    banned = sorted(path for path in src if Path(path).name in BANNED_NAMES)

    line_counts = sorted(((count_lines(REPO_ROOT / path), path) for path in src), reverse=True)
    bands = {label: 0 for _, label in LONG_BANDS}
    for lines, _ in line_counts:
        for threshold, label in LONG_BANDS:
            if lines > threshold:
                bands[label] += 1
                break

    packages = {_package_name(path) for path in src} - {""}
    edges: dict[str, set[str]] = {package: set() for package in packages}
    for path in src:
        package = _package_name(path)
        if not package:
            continue
        for imported in _imports_of(REPO_ROOT / path, _module_name(path)):
            if not (imported.startswith("questorharness") or imported.startswith("questor")):
                continue
            target = _dotted_package(imported)
            if target != package and target in packages:
                edges[package].add(target)
    cycles = _strongly_connected(packages, edges)

    tool_classes = _tool_classes()
    tool_names = {name for _, _, name in tool_classes if name}
    literal_hits: list[str] = []
    for relative in TOOL_RADIUS_FILES:
        path = REPO_ROOT / relative
        if not path.exists():
            raise GuardConfigError(f"tool radius file is missing: {relative}")
        text = read_text(path)
        if any(f'"{name}"' in text or f"'{name}'" in text for name in tool_names):
            literal_hits.append(relative)
    # The registration point always counts: adding a tool means editing it even
    # though it carries no tool-name literal. The consumers count only while
    # they still hard-code names.
    radius = [TOOL_RADIUS_FILES[0], *literal_hits]

    test_stems = {Path(path).stem for path in tests}
    mirrored = [path for path in src_modules if f"test_{Path(path).stem}" in test_stems]

    workflow_text = "\n".join(
        read_text(path) for path in sorted((REPO_ROOT / ".github/workflows").glob("*.yml"))
    )
    in_ci = set()
    for line in workflow_text.splitlines():
        match = re.search(r"scripts/guards/(\w+)\.py", line)
        if match and "--self-test" not in line:
            in_ci.add(match.group(1))

    archive = _tracked("docs-pre-reset-v1")
    root_agents = REPO_ROOT / "AGENTS.md"
    capabilities = [path for path in src_modules if path.startswith("src/questorharness/capabilities/")]
    tools_dir = [path for path in capabilities if path.startswith("src/questorharness/capabilities/tools/")]
    subdirs: dict[str, int] = {}
    for path in capabilities:
        parent_segments = path.rsplit("/", 1)[0].split("/")
        if len(parent_segments) < 5:
            continue
        key = "/".join(parent_segments[:5])
        subdirs[key] = subdirs.get(key, 0) + 1
    wide_subdirs = sorted(key for key, count in subdirs.items() if count >= 2)

    return {
        "src_files": _metric(
            len(src),
            "git ls-files src | *.py",
            modules=len(src_modules),
        ),
        "test_files": _metric(
            len(tests),
            "git ls-files tests | *.py",
            unit=sum(1 for path in tests if path.startswith("tests/unit")),
            integration=sum(1 for path in tests if path.startswith("tests/integration")),
            e2e=sum(1 for path in tests if path.startswith("tests/e2e")),
        ),
        "init_with_logic": _metric(len(with_logic), "regex ^\\s*(async )?(def|class) over tracked __init__.py"),
        "export_heavy_packages": _metric(
            len(heavy),
            "AST literal __all__ per __init__.py, len > 10",
            max=heavy[0][0] if heavy else 0,
            max_file=heavy[0][1] if heavy else "",
        ),
        "packages_without_all": _metric(
            len(top_without_all),
            "top-level packages under src/questorharness without a literal __all__",
            names=top_without_all,
        ),
        "banned_name_files": _metric(len(banned), "basename in ADR-0003 section 3 banned list"),
        "long_files": _metric(
            bands["over_soft_limit"],
            "len(read_text(path).splitlines()) over tracked src/*.py",
            warning_band=bands["warning_band"],
            over_limit=bands["over_limit"],
            max=line_counts[0][0] if line_counts else 0,
            max_file=line_counts[0][1] if line_counts else "",
        ),
        "dependency_cycles": _metric(
            len(cycles),
            "AST import graph at two-level package granularity, Tarjan SCC",
            cycles=[" <-> ".join(component) for component in cycles],
        ),
        "tool_radius": _metric(
            len(radius),
            "shared files a new tool must touch: registration point + consumers with hard-coded names",
            files=radius,
            literal_hits=literal_hits,
        ),
        "mypy_errors": _metric(
            1453,
            "uv run mypy src (historical pin; gate lives in check_mypy_scope.py from W4)",
            gate=False,
            files=251,
        ),
        "pytest_node_ids": _metric(
            1178,
            "uv run pytest -m 'unit or integration' --collect-only -q (owned by baseline_check.py)",
            gate=False,
        ),
        "test_mirror_rate": _metric(
            f"{len(mirrored)}/{len(src_modules)}",
            "tests/**/test_<stem>.py for every non-__init__ src module",
            percent=round(100 * len(mirrored) / len(src_modules), 1) if src_modules else 0.0,
        ),
        "ci_guard_scripts": _metric(
            len(BASELINE_GUARDS),
            "guards present at the baseline; gen_* generators are excluded",
            in_ci=sorted(in_ci),
        ),
        "archive_files": _metric(len(archive), "git ls-files docs-pre-reset-v1"),
        "root_agents": _metric(
            count_lines(root_agents),
            "len(read_text('AGENTS.md').splitlines())",
            bytes=root_agents.stat().st_size,
        ),
        "package_agents": _metric(
            sum(1 for item in _tracked("*AGENTS.md") if item != "AGENTS.md"),
            "git ls-files *AGENTS.md excluding the repository root",
            expected_dirs=[f"{path}/AGENTS.md" for path in PACKAGE_MAP_DIRS],
        ),
        "capabilities_size": _metric(
            len(capabilities),
            "git ls-files src | non-__init__ under capabilities/",
            tool_files=len(tools_dir),
            subdirs_ge2=len(wide_subdirs),
            ratio=round(100 * len(capabilities) / len(src_modules), 1) if src_modules else 0.0,
        ),
    }


def render(metrics: dict[str, dict[str, object]]) -> str:
    head = _git("rev-parse", "HEAD")[0]
    payload = {
        "pin": {"commit": head, "date": "2026-10-23"},
        "caliber": {
            "scan": "git ls-files (never walk the working tree)",
            "lines": "len(text.splitlines())",
            "fanout": "non-__init__ source files",
            "refresh": "manual only: --refresh-baseline --reason <text>",
        },
        "metrics": metrics,
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def write(metrics: dict[str, dict[str, object]], *, overwrite: bool) -> int:
    if TARGET.exists() and not overwrite:
        print(f"baseline already exists: {TARGET.relative_to(REPO_ROOT)}", file=sys.stderr)
        print("use --refresh-baseline --reason <why> to replace it", file=sys.stderr)
        return EXIT_CONFIG
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(render(metrics), encoding="utf-8", newline="\n")
    print(f"structure baseline written: {TARGET.relative_to(REPO_ROOT)}")
    for key in sorted(metrics):
        print(f"  {key}: {metrics[key]['value']}")
    return EXIT_OK


def check() -> int:
    if not TARGET.exists():
        print(f"structure baseline missing: {TARGET.relative_to(REPO_ROOT)}", file=sys.stderr)
        print("run --write to create it", file=sys.stderr)
        return EXIT_CONFIG
    recorded = json.loads(TARGET.read_text(encoding="utf-8"))["metrics"]
    current = collect()
    problems: list[str] = []
    for key in sorted(recorded):
        if key not in current:
            problems.append(f"{key}: recorded but no collector")
            continue
        if not recorded[key].get("gate", True):
            continue
        expected = current[key]["value"]
        actual = recorded[key]["value"]
        if expected != actual:
            problems.append(f"{key}: expected {expected}, got {actual} (recorded baseline is stale)")
    for key in sorted(set(current) - set(recorded)):
        problems.append(f"{key}: collected but not recorded (refresh the baseline)")

    if problems:
        print("structure baseline: DRIFT", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return EXIT_RED
    gated = sum(1 for key in recorded if recorded[key].get("gate", True))
    print(f"structure baseline: OK ({gated} gated metrics match)")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true", help="compare the tree to the baseline (default)")
    action.add_argument("--write", action="store_true", help="create the baseline when it does not exist")
    action.add_argument("--refresh-baseline", action="store_true", help="replace an existing baseline")
    parser.add_argument("--reason", default="", help="why the baseline is being refreshed (required)")
    parser.add_argument(
        "--fail-on-empty",
        action="store_true",
        default=True,
        help="treat an empty scan target as a configuration error (default: on)",
    )
    args = parser.parse_args(argv)

    if args.refresh_baseline and not args.reason.strip():
        print("--refresh-baseline requires --reason <why>", file=sys.stderr)
        return EXIT_CONFIG
    if args.refresh_baseline:
        print(f"refreshing baseline: {args.reason.strip()}")

    try:
        metrics = collect()
    except GuardConfigError as exc:
        print(f"structure baseline: config error: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    if args.write:
        return write(metrics, overwrite=False)
    if args.refresh_baseline:
        return write(metrics, overwrite=True)
    return check()


if __name__ == "__main__":
    raise SystemExit(main())
