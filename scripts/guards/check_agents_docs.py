#!/usr/bin/env python3
"""Keep the three documentation layers honest (plan 01, W7: C1-C6).

Layer contract: the root ``AGENTS.md`` is a signpost, package ``AGENTS.md`` files
state boundaries, and every fact about shape is generated (``TREE.md`` /
``GRAPH.md``). Each check has a red and a green side; C6 is the one that stops a
hand-drawn diagram from coming back.

C1  every critical package has AGENTS.md with 不负责/禁止 and no sibling README.md
C2  the declared public face equals the real one (set comparison, no eyeballs)
C3  every .importlinter contract id is cited in the root dependency rules
C4  CLAUDE.md stays a thin pointer (never a second copy of the rulebook)
C5  every route-table row in the root AGENTS.md points at an existing path
C6  generated documents keep their marker, match --check, and STRUCTURE.md drew
    no dependency edges of its own
"""

from __future__ import annotations

import argparse
import ast
import configparser
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

try:
    from ._guard_kit import EXIT_CONFIG, EXIT_OK, EXIT_RED, count_lines, read_text, run_self_test
except ImportError:  # direct script execution
    from _guard_kit import EXIT_CONFIG, EXIT_OK, EXIT_RED, count_lines, read_text, run_self_test

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKTICK_RE = re.compile(r"`([^`\n]+)`")

try:
    from ._layout_rules import CRITICAL_PACKAGES
except ImportError:  # direct script execution
    from _layout_rules import CRITICAL_PACKAGES

# C1 and R6 guard the same fact, so the list has exactly one owner: the layout
# rules module. Shrinking it is a reviewed decision, not a refactor.
PACKAGE_MAPS = CRITICAL_PACKAGES

REQUIRED_FIELDS = ("职责", "不负责", "公开入口", "拥有的数据", "允许依赖", "不变式", "禁止", "测试", "关键文件")

# Dependency notation that must not come back into STRUCTURE.md.
HAND_DRAWN_MARKERS = ("mermaid", "箭头方向", "──>", "-->", "──", "┌──", "└──")


def _field(text: str, name: str) -> str:
    match = re.search(rf"^\s*{name}[：:]\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _path_tokens(line: str) -> list[str]:
    return [
        token.strip()
        for token in BACKTICK_RE.findall(line)
        if token.strip() and ("/" in token or token.endswith((".py", ".md")))
    ]


def _public_face(module_file: Path) -> tuple[set[str], bool]:
    """Return ``(names, had_literal_all)`` for a module.

    A literal ``__all__`` is the declared face, so it can be compared exactly;
    otherwise the public bindings are the best available answer.
    """

    tree = ast.parse(read_text(module_file))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", None) == "__all__" for target in node.targets
        ):
            if isinstance(node.value, (ast.List, ast.Tuple)):
                found = {item.value for item in node.value.elts if isinstance(item.value, str) and item.value}
                return found, True
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                if not bound.startswith("_"):
                    names.add(bound)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    names.add(target.id)
    return names, False


NAME_SPLIT_RE = re.compile(r"[/、,，]| 和 ")
IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# A backticked span that contains a slash or a dot is a path or a module
# attribute, not a public name, so it must not be mined for names.
PATH_SPAN_RE = re.compile(r"`[^`]*[/.][^`]*`")


def _clean_name(token: str) -> str:
    return token.strip().strip("`“”\\\" ").strip()


def _declared_public_names(line: str) -> set[str]:
    """Names claimed after 导出/提供 or inside （…）, tolerant of list punctuation.

    Path spans are removed before splitting, otherwise ``a/__init__.py`` would
    contribute a phantom name ``a``.
    """

    found: set[str] = set()
    groups = [match.group(1) for match in re.finditer(r"(?:导出|提供)\s*[:：]?\s*([^；;。\n]*)", line)]
    groups += [match.group(1) for match in re.finditer(r"（([^）]*)）", line)]
    for group in groups:
        stripped = PATH_SPAN_RE.sub(" ", group)
        for item in NAME_SPLIT_RE.split(stripped):
            name = _clean_name(item)
            if IDENTIFIER_RE.fullmatch(name):
                found.add(name)
    return found


def check_c1_packages(root: Path) -> list[str]:
    problems: list[str] = []
    for package in PACKAGE_MAPS:
        directory = root / package
        agents = directory / "AGENTS.md"
        if not directory.is_dir():
            problems.append(f"C1 {package}: critical package is missing")
            continue
        if not agents.exists():
            problems.append(f"C1 {package}: missing AGENTS.md")
            continue
        text = read_text(agents)
        for field in REQUIRED_FIELDS:
            if not _field(text, field):
                problems.append(f"C1 {package}: missing field {field}：")
        if (directory / "README.md").exists():
            problems.append(f"C1 {package}: both AGENTS.md and README.md exist")
        for token in _path_tokens(_field(text, "不负责")):
            if not ((root / token).exists() or (directory / token).exists()):
                problems.append(f"C1 {package}: 不负责 points at a missing path: {token}")
    return problems


def _resolve(root: Path, package: str, token: str) -> Path | None:
    """Accept repo-relative, package-relative, and package-prefixed spellings."""

    candidates = [root / token, root / package / token]
    tail = token.split("/", 1)[1] if token.startswith(package.rsplit("/", 1)[-1] + "/") else None
    if tail:
        candidates.append(root / package / tail)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def check_c2_public_face(root: Path) -> list[str]:
    """Every name a map claims must actually be exported by a module it cites.

    One direction on purpose: the plan's red case is a wrong or renamed entry
    point. Coverage of the whole ``__all__`` is not this check's job (that would
    turn a boundary map into a duplicated API listing).
    """

    problems: list[str] = []
    for package in PACKAGE_MAPS:
        agents = root / package / "AGENTS.md"
        if not agents.exists():
            continue
        line = _field(read_text(agents), "公开入口")
        if not line:
            continue
        modules: list[Path] = []
        for token in _path_tokens(line):
            resolved = _resolve(root, package, token)
            if resolved is None:
                problems.append(f"C2 {package}: 公开入口 points at a missing path: {token}")
                continue
            if resolved.name.endswith(".py"):
                modules.append(resolved)
        declared = _declared_public_names(line)
        if not modules or not declared:
            continue
        actual: set[str] = set()
        for module in modules:
            names, _had_all = _public_face(module)
            actual |= names
        missing = sorted(declared - actual)
        if missing:
            shown = ", ".join(sorted({module.relative_to(root).as_posix() for module in modules}))
            problems.append(f"C2 {package}: 公开入口 names not exported by {shown}: {', '.join(missing)}")
    return problems


def contract_ids(root: Path) -> list[str]:
    """The ``[importlinter:contract:<id>]`` names a human would cite."""

    parser = configparser.ConfigParser()
    parser.read(root / ".importlinter", encoding="utf-8")
    return [
        section.split(":")[-1].strip()
        for section in parser.sections()
        if section.startswith("importlinter:contract:")
    ]


def check_c3_contract_names(root: Path) -> list[str]:
    agents = root / "AGENTS.md"
    if not agents.exists():
        return ["C3 root AGENTS.md is missing"]
    text = read_text(agents)
    return [
        f"C3 contract id '{name}' is not cited in the root AGENTS.md"
        for name in contract_ids(root)
        if name not in text
    ]


def check_c4_claude_pointer(root: Path) -> list[str]:
    claude = root / "CLAUDE.md"
    if not claude.exists():
        return []
    lines = count_lines(claude)
    if lines > 3:
        return [f"C4 CLAUDE.md is {lines} lines; it must stay a one-line pointer (<=3)"]
    if "AGENTS.md" not in read_text(claude):
        return ["C4 CLAUDE.md must point at AGENTS.md"]
    return []


def _routing_rows(text: str) -> list[tuple[int, str]]:
    rows: list[tuple[int, str]] = []
    in_section = False
    for number, line in enumerate(text.splitlines(), start=1):
        if line.startswith("## "):
            in_section = line.startswith("## 路由表")
            continue
        if in_section and line.startswith("|"):
            rows.append((number, line))
    return rows


def check_c5_routing(root: Path) -> list[str]:
    agents = root / "AGENTS.md"
    if not agents.exists():
        return ["C5 root AGENTS.md is missing"]
    text = read_text(agents)
    rows = [item for item in _routing_rows(text) if not item[1].startswith("| ---")]
    problems: list[str] = []
    checked = 0
    for number, line in rows:
        tokens = [
            token
            for token in _path_tokens(line)
            if token.startswith(("src/", "docs/", "scripts/", "tests/"))
        ]
        if not tokens:
            continue
        checked += 1
        for token in tokens:
            if not (root / token).exists():
                problems.append(f"C5 AGENTS.md:{number} route points at a missing path: {token}")
    if checked < 8:
        problems.append(f"C5 only {checked} route rows name a repository path; expected at least 8")
    return problems


def check_c6_generated(root: Path, *, run_freshness: bool = True) -> list[str]:
    problems: list[str] = []
    for relative, marker in (
        ("docs/architecture/TREE.md", "generated by scripts/guards/gen_tree.py"),
        ("docs/architecture/GRAPH.md", "generated by scripts/guards/gen_graph.py"),
    ):
        path = root / relative
        if not path.exists():
            problems.append(f"C6 {relative} is missing")
            continue
        if not any(marker in line for line in read_text(path).splitlines()[:4]):
            problems.append(f"C6 {relative} lost its generated-by marker")
    if run_freshness:
        for script in ("scripts/guards/gen_tree.py", "scripts/guards/gen_graph.py"):
            result = subprocess.run(
                [sys.executable, script, "--check"],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if result.returncode != 0:
                detail = (result.stderr + result.stdout).strip()
                problems.append(f"C6 {script} --check failed: {detail[:120]}")
    structure = root / "docs/architecture/STRUCTURE.md"
    if structure.exists():
        text = read_text(structure)
        head = "\n".join(text.splitlines()[:60])
        for marker in HAND_DRAWN_MARKERS:
            if marker in head:
                problems.append(f"C6 STRUCTURE.md draws dependency edges again ({marker})")
        for reference in ("GRAPH.md", "TREE.md"):
            if reference not in text:
                problems.append(f"C6 STRUCTURE.md does not point at {reference}")
    return problems


CHECKS = {
    "C1": check_c1_packages,
    "C2": check_c2_public_face,
    "C3": check_c3_contract_names,
    "C4": check_c4_claude_pointer,
    "C5": check_c5_routing,
}


def collect(root: Path) -> list[str]:
    """Run C1-C6 and return every problem."""

    problems = [problem for function in CHECKS.values() for problem in function(root)]
    return problems + check_c6_generated(root)


def _synthetic_repo(tmp: Path) -> Path:
    """A tree that satisfies C1-C6, so each check can be proven red separately."""

    contract = "config-is-leaf"
    for package in PACKAGE_MAPS:
        directory = tmp / package
        directory.mkdir(parents=True)
        (directory / "__init__.py").write_text('__all__ = ["thing"]\n\nthing = 1\n', encoding="utf-8")
        (directory / "sibling.py").write_text("VALUE = 1\n", encoding="utf-8")
        (directory / "AGENTS.md").write_text(
            "# map\n\n"
            "职责：测试用包。\n"
            f"不负责：具体实现见 `{package}/sibling.py`。\n"
            "公开入口：`__init__.py` 导出 thing。\n"
            "拥有的数据：无。\n"
            "允许依赖：`contracts`。\n"
            "不变式：无。\n"
            "禁止：不要再开类型桶。\n"
            "测试：`uv run pytest -q`\n"
            "关键文件：`__init__.py`、`sibling.py`\n",
            encoding="utf-8",
        )
    docs = tmp / "docs" / "architecture"
    docs.mkdir(parents=True)
    (docs / "TREE.md").write_text(
        "# Source tree map\n\n<!-- generated by scripts/guards/gen_tree.py; do not edit -->\n",
        encoding="utf-8",
    )
    (docs / "GRAPH.md").write_text(
        "# Dependency graph\n\n<!-- generated by scripts/guards/gen_graph.py; do not edit -->\n",
        encoding="utf-8",
    )
    (docs / "STRUCTURE.md").write_text(
        "# Structure\n\nSee `GRAPH.md` and `TREE.md`; edges are generated, not drawn.\n",
        encoding="utf-8",
    )
    (tmp / ".importlinter").write_text(
        "[importlinter]\nroot_packages =\n    questorharness\n\n"
        "[importlinter:contract:config-is-leaf]\n"
        "name = Config must not import runtime\ntype = forbidden\n",
        encoding="utf-8",
    )
    (tmp / "CLAUDE.md").write_text("See `AGENTS.md`.\n", encoding="utf-8")
    rows = "\n".join(f"| 条目 {index} | `{PACKAGE_MAPS[0]}/sibling.py` |" for index in range(8))
    (tmp / "AGENTS.md").write_text(
        f"# AGENTS\n\n## 依赖铁律\n\n`{contract}`\n\n## 路由表\n\n"
        f"| 想改什么 | 去哪里 |\n| --- | --- |\n{rows}\n",
        encoding="utf-8",
    )
    return tmp


def _self_test() -> int:
    """Every check must be silent on a clean tree and loud on a broken one."""

    import tempfile

    def all_checks(root: Path) -> dict[str, list[str]]:
        found = {name: function(root) for name, function in CHECKS.items()}
        found["C6"] = check_c6_generated(root, run_freshness=False)
        return found

    cases: list[tuple[str, bool, str]] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = _synthetic_repo(Path(tmp))
        clean = all_checks(root)
        problems = {name: items for name, items in clean.items() if items}
        cases.append(("clean-tree-passes", not problems, f"{problems}"[:150]))

        (root / PACKAGE_MAPS[1] / "AGENTS.md").unlink()
        second = root / PACKAGE_MAPS[2] / "AGENTS.md"
        second.write_text(
            second.read_text(encoding="utf-8").replace("导出 thing。", "导出 nonexistent_name。"),
            encoding="utf-8",
        )
        (root / "CLAUDE.md").write_text("a\nb\nc\nd\n", encoding="utf-8")
        (root / "docs/architecture/STRUCTURE.md").write_text(
            "# Structure\n\n```mermaid\ngraph TD\nA-->B\n```\n", encoding="utf-8"
        )
        (root / "AGENTS.md").write_text(
            "# AGENTS\n\n## 路由表\n\n| 想改什么 | 去哪里 |\n| --- | --- |\n"
            + "\n".join(f"| 条目 {index} | `src/nope/{index}.py` |" for index in range(8))
            + "\n",
            encoding="utf-8",
        )
        broken = all_checks(root)
        for name in CHECKS:
            cases.append((f"{name}-detects-drift", bool(broken[name]), f"{broken[name][:1]}"[:150]))
        (root / "docs/architecture/TREE.md").write_text("# no marker\n", encoding="utf-8")
        marker = check_c6_generated(root, run_freshness=False)
        cases.append(("C6-detects-lost-marker", any("lost its generated-by" in item for item in marker), f"{marker}"[:150]))
    return run_self_test(cases)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="prove each check can go red and green")
    parser.add_argument(
        "--fail-on-empty",
        action="store_true",
        help="treat a repository without any package map as a configuration error",
    )
    parser.add_argument("--root", default=str(REPO_ROOT), help="repository root to scan")
    args = parser.parse_args(argv)
    if args.self_test:
        return _self_test()

    root = Path(args.root).resolve()
    found = [package for package in PACKAGE_MAPS if (root / package / "AGENTS.md").exists()]
    if args.fail_on_empty and not found:
        print("agents docs guard: config error: no package AGENTS.md found", file=sys.stderr)
        return EXIT_CONFIG

    problems = collect(root)
    if problems:
        print("agents docs guard: documentation drift found:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return EXIT_RED
    print(
        f"agents docs guard: OK (C1-C6 clean, {len(found) + 1} AGENTS.md, "
        f"{len(contract_ids(root))} contract ids cited)"
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
