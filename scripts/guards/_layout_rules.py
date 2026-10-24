#!/usr/bin/env python3
"""Layout rules R1-R8 from ADR-0003 section 8 (plan 01, W2).

The rules live here as pure functions over the tracked tree so both the CLI
(`check_layout.py`) and the contract tests can call them without duplicating the
scanning caliber. Everything goes through ``_guard_kit.tracked_files`` and
``_guard_kit.count_lines``: untracked scratch files never influence a verdict and
line counts always mean ``len(text.splitlines())``.

Rules:
    R1  directory fan-out (fail >30 non-__init__ sources, warn 17-30)
    R2  file lines (fail >1500, ratchet inside 1001-1500 via inline exemption)
    R3  banned file names (ADR-0003 section 3)
    R4  __init__.py facades (fail >40 lines or any def/class)
    R5  exports (top-level package without __all__, or more than the limit)
    R6  package map (AGENTS.md with key files that actually exist)
    R7  test mirror (every non-__init__ source has tests/**/test_<stem>.py)
    R8  function complexity ratchet (cyclomatic >20, pinned budget)

R9 (tool schema enumerability) lives in tests/ci/test_tool_schemas.py and R10
(namespace registries) lives in check_name_registries.py: they need imported
objects, not a static text scan.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

try:
    from ._guard_kit import (
        Exemption,
        count_lines,
        exemption_errors,
        parse_exemptions,
        read_text,
        tracked_files,
    )
except ImportError:  # direct script execution
    from _guard_kit import (  # type: ignore[no-redef]
        Exemption,
        count_lines,
        exemption_errors,
        parse_exemptions,
        read_text,
        tracked_files,
    )

GLOBAL_LINE_LIMIT = 1500
SOFT_LINE_LIMIT = 1000
DIR_FANOUT_FAIL = 30
DIR_FANOUT_WARN = 17
FACADE_LINE_LIMIT = 40
EXPORT_LIMIT = 10
EXPORT_LIMIT_CONTRACTS = 15
COMPLEXITY_LIMIT = 20

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

# Catalog directories are exempt from R1 by review, not by comment: there is no
# file to attach an inline exemption to. Keep this empty until a real catalog
# directory appears (migrations / schemas / vendor).
CATALOG_DIRS: tuple[str, ...] = ()

# The packages that must carry a map: 12 engine domains plus the product package
# (plan 01 W7). Shrinking this list is a reviewed decision, not a refactor.
CRITICAL_PACKAGES = (
    "src/questorharness/bootstrap",
    "src/questorharness/capabilities",
    "src/questorharness/commands",
    "src/questorharness/config",
    "src/questorharness/contracts",
    "src/questorharness/engine",
    "src/questorharness/execution",
    "src/questorharness/platform",
    "src/questorharness/plugins",
    "src/questorharness/providers",
    "src/questorharness/runtime",
    "src/questorharness/surfaces",
    "src/questor",
)

DISTRIBUTIONS = ("questorharness", "questor")

# Exemption budgets: the exact number of inline comments each rule may have.
# This is a ratchet, not a cap: ``collect_with_budgets`` fails when the real
# count differs from the budget in **either** direction, so paying off a piece of
# debt without lowering its number here fails just as loudly as taking on new
# debt. Raising a number is therefore impossible to hide — it turns the check
# red until the matching comment is also removed.
# R5 is 1 rather than 17: the only remaining case is context.compact, which
# exports too much from an entry point that still holds behavior (its split is the
# last W8 unit). Seven pure aggregate facades (swarm, memory, consolidate, auth,
# mcp, sandbox, bridge) keep a pinned cap in AGGREGATE_FACADE_EXPORT_CAPS because
# pruning them would push callers inside the package. Nine top-level packages now
# declare their face instead of relying on dir(): eight expose nothing at the
# package root (submodule imports are the API) and platform exposes five names out
# of the twelve it binds.
# R4 is 1 rather than 14: W8 examined every exempted facade instead of assuming
# each one needed splitting. Eight only re-export (seven pure lazy __getattr__
# tables plus runtime.swarm's eager-import hybrid), three were split (skills.bundled
# -> discovery.py, memory.session -> store.py + document.py, memory.extract ->
# records.py + guard.py + extraction.py), and platform is a reviewed implementation
# facade held by a line cap in FACADE_IMPLEMENTATION_PACKAGES. Only context.compact
# still carries behavior worth relocating behind an exemption.
# R3 is 0: the last banned name, ``surfaces/channels/helpers.py``, was retired once its
# own stated precondition was checked against the code and found already satisfied --
# exactly one in-repo importer (the Feishu adapter), no patch strings. It became
# ``filenames.py`` and ``message_chunks.py`` plus the deletion of a zero-caller
# ``get_data_path`` alias, so the bucket is gone rather than renamed (ledger #127).
# R7 is 154, the plan's target: one inline note per module that no test file names.
# This number is only ever paid with mirror tests that go red when the behavior changes.
# A candidate whose whole surface is Protocol or TypedDict declarations
# (capabilities/schedule ports, contracts/mcp) stays exempted on purpose -- a test there
# could only assert that an interface exists, which would lower the number while pinning
# no decision (plan 01 ledger #120).
EXEMPTION_BUDGET: dict[str, int] = {
    "R2": 1,
    "R3": 0,
    "R4": 1,
    "R5": 1,
    "R7": 154,
    "R8": 31,
}

# Functions above the complexity limit that live in files carrying an R8
# exemption. Held to an exact count for the same reason as the budgets above.
R8_EXEMPT_FUNCTIONS = 39

PINNED_LINES_RE = re.compile(r"(\d+)\s+lines")

# Statements that do work rather than name things. A facade may re-export eagerly
# or lazily through ``__getattr__``; either way it must not compute (ADR-0003 §1).
COMPUTING_STATEMENTS: tuple[type[ast.AST], ...] = (
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.Try,
    ast.With,
    ast.AsyncWith,
    ast.ClassDef,
    ast.Match,
)
NESTABLE_STATEMENTS: tuple[type[ast.AST], ...] = COMPUTING_STATEMENTS + (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
)

# A lazy facade is a name table, so its honest size bound scales with the number
# of exported names instead of a constant that ignores them.
LAZY_FACADE_BASE_LINES = 40
LAZY_FACADE_LINES_PER_EXPORT = 8

# Reviewed R4 exceptions: leaf utility packages whose entry point *is* the
# implementation of one cohesive concern. W8 inspected each candidate and chose
# not to split these, because moving the definition off the package attribute
# would silently break the ``questorharness.platform.*`` patch targets that tests
# rely on, while adding an indirection readers do not need to find the code.
# The value is a hard line cap: grow past it and the entry point is debt again.
FACADE_IMPLEMENTATION_PACKAGES: dict[str, int] = {
    "src/questorharness/platform": 120,
}

# Pure aggregate facades: ``__init__.py`` declares no names of its own and only
# re-exports a family of siblings. Their export count is the point of the package,
# so it gets a pinned, shrink-only cap instead of an inline exemption (W8).
AGGREGATE_FACADE_EXPORT_CAPS: dict[str, int] = {
    "src/questorharness/capabilities/memory": 12,
    "src/questorharness/capabilities/memory/consolidate": 13,
    "src/questorharness/providers/auth": 11,
    "src/questorharness/providers/mcp": 11,
    "src/questorharness/providers/sandbox": 12,
    "src/questorharness/runtime/bridge": 11,
    "src/questorharness/runtime/swarm": 23,
}


def _facade_shape(tree: ast.Module) -> tuple[str, str, int]:
    """Classify a package entry as ``eager`` / ``lazy`` / ``behavior``.

    Returns the shape, the offending construct for ``behavior``, and the number of
    names in a literal ``__all__`` (0 when there is none, which keeps the strict
    line cap).
    """

    exported = 0
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", None) == "__all__" for target in node.targets
        ) and isinstance(node.value, (ast.List, ast.Tuple)):
            exported = len(node.value.elts)

    for node in tree.body:
        if isinstance(node, COMPUTING_STATEMENTS):
            return "behavior", type(node).__name__, exported
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name != "__getattr__":
            return "behavior", f"def {node.name}()", exported

    functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if not functions:
        return "eager", "", exported
    for function in functions:
        for inner in ast.walk(function):
            if inner is function:
                continue
            if isinstance(inner, NESTABLE_STATEMENTS):
                return "behavior", f"__getattr__ contains {type(inner).__name__}", exported
    return "lazy", "", exported


def _facade_line_limit(shape: str, exported: int) -> int:
    if shape != "lazy" or exported <= 0:
        return FACADE_LINE_LIMIT
    return LAZY_FACADE_BASE_LINES + LAZY_FACADE_LINES_PER_EXPORT * exported
KEY_FILES_RE = re.compile(r"关键文件[：:]\s*(.+)")
BACKTICK_RE = re.compile(r"`([^`\n]+)`")


@dataclass(frozen=True)
class Violation:
    """One rule breach. ``severity`` is ``fail`` (blocking) or ``warn``."""

    rule: str
    path: str
    message: str
    line: int = 0
    severity: str = "fail"

    def render(self) -> str:
        location = f"{self.path}:{self.line}" if self.line else self.path
        return f"{self.rule} {location}: {self.message}"


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _source_files(root: Path) -> list[Path]:
    return tracked_files(root, ("src",))


def _literal_exports(tree: ast.Module) -> list[str] | None:
    """Return the declared ``__all__``, or None when the package has none.

    Annotated form (``__all__: list[str] = [...]``) counts too: ignoring it would
    let a package dodge the export rules by adding a type annotation.
    """

    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            targets: list[ast.expr] = [node.target]
            value = node.value
        elif isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        else:
            continue
        if not any(getattr(target, "id", None) == "__all__" for target in targets):
            continue
        if value is not None and isinstance(value, (ast.List, ast.Tuple)):
            return [item.value for item in value.elts if isinstance(item, ast.Constant)]
        return None
    return None


def _cyclomatic(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Count decision points, never descending into nested functions or classes."""
    total = 1
    stack: list[ast.AST] = list(node.body)
    branches = (
        ast.If,
        ast.For,
        ast.AsyncFor,
        ast.While,
        ast.ExceptHandler,
        ast.With,
        ast.AsyncWith,
        ast.Assert,
        ast.IfExp,
    )
    while stack:
        current = stack.pop()
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(current, branches):
            total += 1
        elif isinstance(current, ast.BoolOp):
            total += len(current.values) - 1
        elif isinstance(current, ast.comprehension):
            total += 1
        stack.extend(ast.iter_child_nodes(current))
    return total


def rule_r1_fanout(root: Path) -> list[Violation]:
    """Directory fan-out: more than 30 sources is a catalog, 17-30 is a warning."""
    violations: list[Violation] = []
    counts: Counter[str] = Counter()
    for path in _source_files(root):
        if path.name == "__init__.py":
            continue
        relative_dir = _relative(path.parent, root)
        if relative_dir in CATALOG_DIRS:
            continue
        counts[relative_dir] += 1
    for directory, count in sorted(counts.items()):
        if count > DIR_FANOUT_FAIL:
            violations.append(
                Violation("R1", directory, f"{count} source files > {DIR_FANOUT_FAIL}")
            )
        elif count >= DIR_FANOUT_WARN:
            violations.append(
                Violation(
                    "R1",
                    directory,
                    f"{count} source files in the warning band {DIR_FANOUT_WARN}-{DIR_FANOUT_FAIL}",
                    severity="warn",
                )
            )
    return violations


def rule_r2_lines(root: Path) -> list[Violation]:
    """Line budget with a per-file ratchet in the 1001-1500 band."""
    violations: list[Violation] = []
    for path in _source_files(root):
        relative = _relative(path, root)
        lines = count_lines(path)
        exemption = parse_exemptions(path).get("R2")
        if lines > GLOBAL_LINE_LIMIT:
            violations.append(
                Violation("R2", relative, f"{lines} lines > {GLOBAL_LINE_LIMIT}")
            )
            continue
        if lines > SOFT_LINE_LIMIT:
            if exemption is None:
                violations.append(
                    Violation(
                        "R2",
                        relative,
                        f"{lines} lines in {SOFT_LINE_LIMIT + 1}-{GLOBAL_LINE_LIMIT} without an R2 exemption",
                    )
                )
                continue
            match = PINNED_LINES_RE.search(exemption.reason)
            if match is None:
                violations.append(
                    Violation("R2", relative, "R2 exemption must pin the current count, e.g. '1166 lines until W8'", exemption.line)
                )
                continue
            pinned = int(match.group(1))
            if lines > pinned:
                violations.append(
                    Violation("R2", relative, f"{lines} lines > pinned {pinned} (the ratchet only goes down)")
                )
            continue
        if exemption is not None:
            violations.append(
                Violation(
                    "R2",
                    relative,
                    f"stale R2 exemption: file is {lines} lines (<= {SOFT_LINE_LIMIT}), delete the comment",
                    exemption.line,
                )
            )
    return violations


def case_collisions(relative_paths: Sequence[str]) -> list[tuple[str, str]]:
    """Pairs of relative paths that collide under casefolding.

    Pure so it can be tested: a developer on Windows cannot create the two files
    this detects, which is precisely why it must not be verified by hand.
    """

    seen: dict[str, str] = {}
    found: list[tuple[str, str]] = []
    for relative in relative_paths:
        key = relative.casefold()
        previous = seen.get(key)
        if previous is not None and previous != relative:
            found.append((previous, relative))
            continue
        seen[key] = relative
    return found


def case_collision_problems(root: Path) -> list[Violation]:
    """Two tracked paths that differ only by case are a Windows landmine.

    On a case-insensitive filesystem ``git mv manager.py Manager.py`` can appear to
    succeed while the old name keeps importing, so renames - the W9 wave - need this
    checked before they are trusted. It is reported as R3 because a collision is
    exactly the ambiguity that rule is about.
    """

    tracked = [
        _relative(path, root)
        for path in tracked_files(root, ("src", "tests", "scripts", "docs"))
    ]
    return [
        Violation(
            "R3",
            second,
            "path collides case-insensitively with " + first,
        )
        for first, second in case_collisions(tracked)
    ]


def rule_r3_names(root: Path) -> list[Violation]:
    """Banned file names from ADR-0003 section 3, plus case-insensitive collisions."""
    violations: list[Violation] = []
    for path in _source_files(root):
        if path.name not in BANNED_NAMES:
            continue
        if "R3" in parse_exemptions(path):
            continue
        violations.append(
            Violation("R3", _relative(path, root), f"banned file name {path.name}")
        )
    violations.extend(case_collision_problems(root))
    return violations


def rule_r4_facade(root: Path) -> list[Violation]:
    """``__init__.py`` stays a facade: re-export only, and no unbounded growth.

    Two shapes are legal. An **eager** facade is imports plus ``__all__`` and stays
    under ``FACADE_LINE_LIMIT``. A **lazy** facade routes names through
    ``__getattr__``; that routing is re-export, not behavior, so it is allowed —
    with a size bound that grows with the declared exports instead of pretending
    ten names fit in forty lines. Anything that computes (loops, try, with, class,
    a second function, or logic inside the dispatcher) is a violation.
    """

    violations: list[Violation] = []
    seen_allowed: set[str] = set()
    for path in _source_files(root):
        if path.name != "__init__.py":
            continue
        if not path.exists():
            # git ls-files lists staged paths; a file deleted but not yet unstaged
            # must not crash the guard.
            continue
        text = read_text(path)
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        shape, detail, exported = _facade_shape(tree)
        lines = len(text.splitlines())
        relative = _relative(path, root)
        # The allowlist is keyed by package, because the reviewed decision is
        # about the package's entry point, not about one accidental file path.
        package_key = relative.removesuffix("/__init__.py")
        allowed_lines = FACADE_IMPLEMENTATION_PACKAGES.get(package_key)
        if allowed_lines is not None:
            seen_allowed.add(package_key)
            if lines > allowed_lines:
                violations.append(
                    Violation(
                        "R4",
                        relative,
                        f"reviewed implementation facade grew to {lines} > {allowed_lines};"
                        " split it or raise the cap in review",
                    )
                )
                continue
            # The exception exists because the entry point holds behavior. Once it
            # would pass the ordinary facade test, the exception is doing nothing
            # and must be dropped rather than inherited forever.
            limit = _facade_line_limit(shape, exported)
            if shape != "behavior" and lines <= limit:
                violations.append(
                    Violation(
                        "R4",
                        relative,
                        "reviewed implementation exception no longer needed (entry point is a clean"
                        " facade); drop the FACADE_IMPLEMENTATION_PACKAGES entry",
                    )
                )
            continue
        limit = _facade_line_limit(shape, exported)
        if shape == "behavior":
            problem = f"facade contains behavior ({detail})"
        elif lines > limit:
            problem = f"{lines} lines > {limit} ({shape} facade limit)"
        else:
            continue
        if "R4" in parse_exemptions(path):
            continue
        violations.append(Violation("R4", relative, problem))
    # A missing package directory means we are scanning a partial or synthetic
    # tree, not that the reviewed exception went stale.
    for package in sorted(set(FACADE_IMPLEMENTATION_PACKAGES) - seen_allowed):
        if not (root / package).is_dir():
            continue
        violations.append(
            Violation("R4", package, "reviewed implementation facade lost its entry point; drop the allowlist entry")
        )
    return violations


def rule_r5_exports(root: Path) -> list[Violation]:
    """Exports: top-level packages need ``__all__``; nobody exports more than the limit.

    A pure aggregate facade (zero own definitions, re-exporting a family of
    siblings) is allowed a per-package cap instead of an inline exemption:
    pruning its names would push callers past the facade and onto module paths
    inside the package, which is the opposite of what a facade is for. The cap
    may only be met, never exceeded, and must be dropped once it stops mattering.
    """

    violations: list[Violation] = []
    top_level: list[Path] = []
    for distribution in DISTRIBUTIONS:
        base = root / "src" / distribution
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            init = child / "__init__.py"
            if child.is_dir() and init.exists():
                top_level.append(init)

    for init in top_level:
        tree = ast.parse(read_text(init))
        exports = _literal_exports(tree)
        if exports is not None:
            continue
        if "R5" in parse_exemptions(init):
            continue
        violations.append(
            Violation("R5", _relative(init, root), "top-level package has no literal __all__")
        )

    for path in _source_files(root):
        if path.name != "__init__.py":
            continue
        exports = _literal_exports(ast.parse(read_text(path)))
        if exports is None:
            continue
        relative = _relative(path, root)
        package_key = relative.removesuffix("/__init__.py")
        limit = EXPORT_LIMIT_CONTRACTS if "/contracts/" in relative else EXPORT_LIMIT
        pinned = AGGREGATE_FACADE_EXPORT_CAPS.get(package_key)
        if pinned is not None:
            if len(exports) > pinned:
                violations.append(
                    Violation(
                        "R5",
                        relative,
                        f"{len(exports)} exports > aggregate facade cap {pinned} for {package_key}",
                    )
                )
            elif len(exports) <= limit:
                # The cap exists because this facade legitimately aggregates a
                # family. Once it fits the ordinary limit the exception is dead
                # weight and must be removed rather than kept as a free pass.
                violations.append(
                    Violation(
                        "R5",
                        relative,
                        f"aggregate facade cap is no longer needed ({len(exports)} exports <= {limit});"
                        " drop the AGGREGATE_FACADE_EXPORT_CAPS entry",
                    )
                )
            continue
        if len(exports) <= limit:
            continue
        if "R5" in parse_exemptions(path):
            continue
        violations.append(
            Violation("R5", relative, f"{len(exports)} exports > {limit}")
        )
    # No staleness report for caps whose package is absent from this tree: an
    # unused cap grants nothing (it only participates when the facade is present),
    # and demanding every scanned tree contain all seven packages would make the
    # rule unusable on partial checkouts.
    return violations


def rule_r6_maps(root: Path) -> list[Violation]:
    """Every critical package carries a map whose key files exist."""
    violations: list[Violation] = []
    for package in CRITICAL_PACKAGES:
        directory = root / package
        if not directory.is_dir():
            violations.append(Violation("R6", package, "critical package is missing"))
            continue
        agents = directory / "AGENTS.md"
        readme = directory / "README.md"
        if not agents.exists():
            violations.append(Violation("R6", package, "missing AGENTS.md"))
            continue
        if readme.exists():
            violations.append(
                Violation("R6", package, "both README.md and AGENTS.md exist; keep one map")
            )
        text = read_text(agents)
        match = KEY_FILES_RE.search(text)
        if match is None:
            violations.append(
                Violation("R6", _relative(agents, root), "missing '关键文件：' line")
            )
            continue
        tokens = [token.strip() for token in BACKTICK_RE.findall(match.group(1))]
        paths = [token for token in tokens if "/" in token or token.endswith(".py")]
        existing = [token for token in paths if (directory / token).exists()]
        missing = [token for token in paths if not (directory / token).exists()]
        if missing:
            violations.append(
                Violation("R6", _relative(agents, root), f"key files do not exist: {', '.join(missing)}")
            )
        if len(existing) < 2:
            violations.append(
                Violation(
                    "R6",
                    _relative(agents, root),
                    f"needs at least 2 existing key files, found {len(existing)}",
                )
            )
    return violations


def rule_r7_mirror(root: Path) -> list[Violation]:
    """Every source module has a ``tests/**/test_<stem>.py`` mirror."""
    violations: list[Violation] = []
    test_stems = {path.stem for path in tracked_files(root, ("tests",))}
    for path in _source_files(root):
        if path.name == "__init__.py":
            continue
        if f"test_{path.stem}" in test_stems:
            continue
        if "R7" in parse_exemptions(path):
            continue
        violations.append(
            Violation("R7", _relative(path, root), f"no tests/**/test_{path.stem}.py mirror")
        )
    return violations


def rule_r8_complexity(root: Path) -> tuple[list[Violation], int]:
    """Cyclomatic complexity above 20 fails unless the file carries an R8 exemption.

    Returns the violations plus the number of offenders that were exempted, so
    the caller can hold the exempted set to a pinned budget.
    """
    violations: list[Violation] = []
    exempted = 0
    for path in _source_files(root):
        tree = ast.parse(read_text(path))
        exempt = "R8" in parse_exemptions(path)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            score = _cyclomatic(node)
            if score <= COMPLEXITY_LIMIT:
                continue
            if exempt:
                exempted += 1
                continue
            violations.append(
                Violation(
                    "R8",
                    _relative(path, root),
                    f"{node.name} has cyclomatic complexity {score} > {COMPLEXITY_LIMIT}",
                    node.lineno,
                )
            )
    return violations, exempted


def collect(root: Path) -> list[Violation]:
    """Run R1-R8 and return every violation (warnings included)."""
    violations: list[Violation] = []
    violations.extend(rule_r1_fanout(root))
    violations.extend(rule_r2_lines(root))
    violations.extend(rule_r3_names(root))
    violations.extend(rule_r4_facade(root))
    violations.extend(rule_r5_exports(root))
    violations.extend(rule_r6_maps(root))
    violations.extend(rule_r7_mirror(root))
    r8_violations, _ = rule_r8_complexity(root)
    violations.extend(r8_violations)
    return violations


def budget_problems(
    counts: dict[str, int],
    exempted_functions: int,
    budget: dict[str, int] | None = None,
    pinned_functions: int | None = None,
) -> list[str]:
    """Compare live exemption counts to the pinned ratchet, both directions.

    Kept as a pure function so the contract tests can prove the ``<`` direction
    (debt paid, budget not lowered) without rewriting the real repository.
    """
    budget = EXEMPTION_BUDGET if budget is None else budget
    pinned = R8_EXEMPT_FUNCTIONS if pinned_functions is None else pinned_functions
    problems: list[str] = []
    if exempted_functions != pinned:
        problems.append(
            f"R8: {exempted_functions} exempted complex functions != pinned {pinned} "
            "(simplify one and lower the number in the same change)"
        )
    for rule, limit in sorted(budget.items()):
        actual = counts.get(rule, 0)
        if actual > limit:
            problems.append(f"{rule}: {actual} exemptions > budget {limit} — debt was added")
        elif actual < limit:
            problems.append(
                f"{rule}: {actual} exemptions < budget {limit} — the debt is gone but the "
                "budget was not lowered in the same change"
            )
    return problems


def collect_with_budgets(
    root: Path,
    *,
    budget: dict[str, int] | None = None,
    pinned_functions: int | None = None,
) -> tuple[list[Violation], list[str]]:
    """Run the rules and also check exemption syntax and per-rule budgets.

    ``budget`` / ``pinned_functions`` exist so the contract tests can drive a
    synthetic repository (which has no exemptions at all) against the empty
    ratchet; the CLI leaves them unset and gets the real one.
    """
    violations = collect(root)
    problems: list[str] = []

    _, r8_exempted = rule_r8_complexity(root)

    counts: Counter[str] = Counter()
    for path in _source_files(root):
        for message in exemption_errors(path):
            problems.append(f"{_relative(path, root)}: {message}")
        for rule in parse_exemptions(path):
            counts[rule] += 1

    problems.extend(
        budget_problems(
            dict(counts),
            r8_exempted,
            budget=budget,
            pinned_functions=pinned_functions,
        )
    )
    return violations, problems


def exemptions_by_rule(root: Path) -> dict[str, int]:
    """Return how many inline exemptions each rule currently has."""
    counts: Counter[str] = Counter()
    for path in _source_files(root):
        for rule in parse_exemptions(path):
            counts[rule] += 1
    return dict(sorted(counts.items()))


def _unused(_: Exemption) -> None:
    """Keep the Exemption import meaningful for type checkers reading this module."""


__all__ = [
    "CRITICAL_PACKAGES",
    "EXEMPTION_BUDGET",
    "R8_EXEMPT_FUNCTIONS",
    "Violation",
    "budget_problems",
    "collect",
    "collect_with_budgets",
    "exemptions_by_rule",
    "rule_r1_fanout",
    "rule_r2_lines",
    "rule_r3_names",
    "case_collisions",
    "rule_r4_facade",
    "rule_r5_exports",
    "rule_r6_maps",
    "rule_r7_mirror",
    "rule_r8_complexity",
]
