#!/usr/bin/env python3
"""Tie test-infrastructure adoption to the suite scale that justifies it.

Sharding and impact-analysis tooling pays permanent maintenance rent: duration
baselines rot when the test set changes, hash shards drift apart, and dynamic
impact analysis produces false greens. docs/operations/ci.md pins the policy in
BOTH directions — below the sharding threshold the tools are banned, at or
above it their absence is the violation. Suite size comes from the committed
pytest baseline summary, so this guard is one file read and never runs pytest.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import tomllib
from collections.abc import Sequence
from pathlib import Path

try:
    from ._guard_kit import EXIT_CONFIG, EXIT_OK, EXIT_RED, GuardConfigError, read_text, run_self_test
except ImportError:  # direct script execution
    from _guard_kit import EXIT_CONFIG, EXIT_OK, EXIT_RED, GuardConfigError, read_text, run_self_test

REPO_ROOT = Path(__file__).resolve().parents[2]

# 与 docs/operations/ci.md 的触发表是同一份决定：改这里必须同一刀改文档，反之亦然。
SHARDING_THRESHOLD_TESTS = 5000
# 阈值之下即"过早负债"的工具：维护费按周付，收益在 5k 例之前不存在。
PREMATURE_TOOLS = ("pytest-xdist", "pytest-testmon", "pytest-picked", "pytest-split")
# 阈值之上，出现其一才算"分片已就位"。
SHARDING_TOOLS = ("pytest-xdist", "pytest-split")
# addopts 里出现这些 token 等价于已装分片/影响面工具。
_PREMATURE_TOKENS = ("-n", "--numprocesses", "--splits", "--testmon")
_SHARDING_TOKENS = ("-n", "--numprocesses", "--splits")
# crewAI / deer-flow 式的时长基线：测试集一变就腐烂，阈值之下禁止存在。
_DURATION_GLOB = ".test_durations*"


def _normalize_dep(entry: str) -> str:
    return re.split(r"[<>=!~\[;\s]", entry, maxsplit=1)[0].strip().lower().replace("_", "-")


def _pyproject_data(root: Path) -> dict:
    path = root / "pyproject.toml"
    if not path.exists():
        raise GuardConfigError(f"missing pyproject.toml: {path}")
    return tomllib.loads(read_text(path))


def _suite_size(root: Path) -> int:
    path = root / "tests" / "fixtures" / "baseline" / "summary.json"
    if not path.exists():
        raise GuardConfigError(f"missing pytest baseline summary: {path}")
    pytest_summary = json.loads(read_text(path)).get("pytest")
    total = pytest_summary.get("total") if isinstance(pytest_summary, dict) else None
    if not isinstance(total, int) or total < 0:
        raise GuardConfigError(f"baseline summary has no integer 'pytest.total': {path}")
    return total


def _dev_dependencies(root: Path) -> set[str]:
    optional = _pyproject_data(root).get("project", {}).get("optional-dependencies", {})
    deps: set[str] = set()
    for group in ("dev", "test"):
        for entry in optional.get(group, []):
            if isinstance(entry, str):
                deps.add(_normalize_dep(entry))
    return deps


def _addopts_tokens(root: Path) -> list[str]:
    ini = _pyproject_data(root).get("tool", {}).get("pytest", {}).get("ini_options", {})
    return str(ini.get("addopts", "")).split()


def _wiring_text(root: Path) -> str:
    """Concatenate Makefile + CI workflows: the places where sharding gets wired."""
    chunks: list[str] = []
    candidates = [root / "Makefile", *sorted((root / ".github" / "workflows").glob("*.y*ml"))]
    for candidate in candidates:
        if candidate.exists():
            chunks.append(read_text(candidate))
    return "\n".join(chunks)


def check(root: Path) -> list[str]:
    total = _suite_size(root)
    deps = _dev_dependencies(root)
    tokens = _addopts_tokens(root)
    problems: list[str] = []

    if total < SHARDING_THRESHOLD_TESTS:
        for tool in PREMATURE_TOOLS:
            if tool in deps:
                problems.append(
                    f"suite is {total} tests (< {SHARDING_THRESHOLD_TESTS}): "
                    f"'{tool}' in dev dependencies is premature rent — see docs/operations/ci.md"
                )
        for token in _PREMATURE_TOKENS:
            if token in tokens:
                problems.append(
                    f"suite is {total} tests: pytest addopts contains '{token}' — see docs/operations/ci.md"
                )
        for path in sorted(root.glob(_DURATION_GLOB)):
            problems.append(
                f"suite is {total} tests: '{path.name}' rots whenever the test set changes "
                "— see docs/operations/ci.md"
            )
        return problems

    # 阈值之上：依赖、addopts、Makefile 或 CI 任一处出现分片即算就位。
    wired = any(tool in deps for tool in SHARDING_TOOLS)
    wired = wired or any(token in tokens for token in _SHARDING_TOKENS)
    if not wired:
        wiring = _wiring_text(root)
        wired = (
            any(tool in wiring for tool in SHARDING_TOOLS)
            or "--splits" in wiring
            or "-n auto" in wiring
        )
    if not wired:
        problems.append(
            f"suite crossed {SHARDING_THRESHOLD_TESTS} tests: adopt sharding per docs/operations/ci.md "
            "(pytest-split least_duration or pytest-xdist); to move the threshold, change this guard "
            "and docs/operations/ci.md in the same commit"
        )
    return problems


def _write_tree(
    root: Path,
    *,
    total: int,
    dev_extra: tuple[str, ...] = (),
    addopts: str = "",
    duration_file: bool = False,
    makefile: str | None = None,
) -> None:
    """One synthetic repository exercising every input the guard reads."""
    deps = ", ".join(['"pytest>=8.0.0"', *(f'"{item}"' for item in dev_extra)])
    addopts_line = f'addopts = \'-m "not e2e" {addopts}\'\n' if addopts else 'addopts = \'-m "not e2e"\'\n'
    (root / "pyproject.toml").write_text(
        "[project]\n"
        'name = "synthetic"\n\n'
        "[project.optional-dependencies]\n"
        f"dev = [{deps}]\n\n"
        "[tool.pytest.ini_options]\n"
        f"{addopts_line}",
        encoding="utf-8",
    )
    baseline = root / "tests" / "fixtures" / "baseline"
    baseline.mkdir(parents=True)
    (baseline / "summary.json").write_text(
        json.dumps({"pytest": {"total": total, "deselected": 0}}), encoding="utf-8"
    )
    if duration_file:
        (root / ".test_durations").write_text("{}", encoding="utf-8")
    if makefile is not None:
        (root / "Makefile").write_text(makefile, encoding="utf-8")


def _self_test() -> int:
    cases: list[tuple[str, bool, str]] = []
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)

        clean = base / "clean"
        clean.mkdir()
        _write_tree(clean, total=1931)
        cases.append(("below-threshold-clean-is-green", check(clean) == [], f"{check(clean)}"))

        xdist_dep = base / "xdist-dep"
        xdist_dep.mkdir()
        _write_tree(xdist_dep, total=1931, dev_extra=("pytest-xdist>=3.0.0",))
        cases.append(
            (
                "below-threshold-xdist-dep-is-red",
                any("pytest-xdist" in item for item in check(xdist_dep)),
                f"{check(xdist_dep)}",
            )
        )

        sharded_addopts = base / "sharded-addopts"
        sharded_addopts.mkdir()
        _write_tree(sharded_addopts, total=1931, addopts="-n auto")
        cases.append(
            (
                "below-threshold-parallel-addopts-is-red",
                any("addopts" in item for item in check(sharded_addopts)),
                f"{check(sharded_addopts)}",
            )
        )

        durations = base / "durations"
        durations.mkdir()
        _write_tree(durations, total=1931, duration_file=True)
        cases.append(
            (
                "below-threshold-duration-file-is-red",
                any(".test_durations" in item for item in check(durations)),
                f"{check(durations)}",
            )
        )

        unsharded = base / "unsharded"
        unsharded.mkdir()
        _write_tree(unsharded, total=SHARDING_THRESHOLD_TESTS)
        cases.append(
            (
                "at-threshold-without-sharding-is-red",
                any("crossed" in item for item in check(unsharded)),
                f"{check(unsharded)}",
            )
        )

        sharded = base / "sharded"
        sharded.mkdir()
        _write_tree(sharded, total=SHARDING_THRESHOLD_TESTS, makefile="test:\n\tpytest --splits 4 --group 1\n")
        cases.append(("at-threshold-with-sharding-is-green", check(sharded) == [], f"{check(sharded)}"))

        try:
            _suite_size(base / "no-baseline")
        except GuardConfigError:
            missing_rejected = True
        else:
            missing_rejected = False
        cases.append(
            ("missing-baseline-is-config-error", missing_rejected, "absent summary.json raises GuardConfigError")
        )

    return run_self_test(cases)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test", action="store_true", help="prove the guard goes red and green on synthetic trees"
    )
    args = parser.parse_args(argv)
    if args.self_test:
        return _self_test()

    try:
        problems = check(REPO_ROOT)
    except GuardConfigError as exc:
        print(f"test-infra-policy: CONFIG ERROR: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    if problems:
        for item in problems:
            print(f"test-infra-policy: {item}")
        return EXIT_RED
    print(
        f"test-infra-policy: OK (suite={_suite_size(REPO_ROOT)} tests, "
        f"threshold={SHARDING_THRESHOLD_TESTS})"
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
