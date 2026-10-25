#!/usr/bin/env python3
"""Single entry point for every blocking guard.

CI and pre-commit both call this script, so the list of guards can never fork
into two hand-maintained copies. Order is fixed and cheap-first: self-tests
prove each guard can still go red, the real runs then decide.

Usage:
    uv run python scripts/check.py            # everything (CI)
    uv run python scripts/check.py --fast     # skip the slow snapshot checks (pre-commit)
    uv run python scripts/check.py --list     # print the step table
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


@dataclass(frozen=True)
class Step:
    """One blocking command. ``slow`` steps are skipped by ``--fast``."""

    name: str
    argv: tuple[str, ...]
    slow: bool = False


# Order: eleven guard self-tests first (each proves its guard can still go red),
# then the live guards, then the generated-doc byte compares, then the
# type/surface checks, and finally baseline-check — the only slow step, which
# additionally pins pytest collection counts and node ids in CI.
STEPS: tuple[Step, ...] = (
    Step("kit-self-test", (PYTHON, "scripts/guards/_guard_kit.py", "--self-test")),
    Step("thread-leak-self-test", (PYTHON, "scripts/guards/check_thread_leak.py", "--self-test")),
    Step("secret-self-test", (PYTHON, "scripts/guards/check_secret_projection.py", "--self-test")),
    Step("docrefs-self-test", (PYTHON, "scripts/guards/check_doc_cross_refs.py", "--self-test")),
    Step("layout-self-test", (PYTHON, "scripts/guards/check_layout.py", "--self-test")),
    Step("registries-self-test", (PYTHON, "scripts/guards/check_name_registries.py", "--self-test")),
    Step("agents-self-test", (PYTHON, "scripts/guards/check_agents_docs.py", "--self-test")),
    Step("agents-size-self-test", (PYTHON, "scripts/guards/check_agents_md_size.py", "--self-test")),
    Step("codeowners-self-test", (PYTHON, "scripts/guards/check_codeowners.py", "--self-test")),
    Step("orphan-self-test", (PYTHON, "scripts/guards/check_orphan_modules.py", "--self-test")),
    Step("test-infra-self-test", (PYTHON, "scripts/guards/check_test_infra_policy.py", "--self-test")),
    Step("thread-leak", (PYTHON, "scripts/guards/check_thread_leak.py", "--fail-on-empty")),
    Step("secret-projection", (PYTHON, "scripts/guards/check_secret_projection.py", "--fail-on-empty")),
    Step("doc-cross-refs", (PYTHON, "scripts/guards/check_doc_cross_refs.py", "--fail-on-empty")),
    Step("layout", (PYTHON, "scripts/guards/check_layout.py", "--fail-on-empty")),
    Step("agents-docs", (PYTHON, "scripts/guards/check_agents_docs.py", "--fail-on-empty")),
    Step("agents-size", (PYTHON, "scripts/guards/check_agents_md_size.py")),
    Step("codeowners", (PYTHON, "scripts/guards/check_codeowners.py", "--fail-on-empty")),
    # Report-only for now (plan 01 W10): the list has to be reviewed before a
    # non-empty result becomes a failure.
    Step("orphan-report", (PYTHON, "scripts/guards/check_orphan_modules.py", "--fail-on-empty")),
    Step("tool-radius", (PYTHON, "scripts/guards/check_tool_radius.py", "--fail-on-empty")),
    Step("name-registries", (PYTHON, "scripts/guards/check_name_registries.py", "--fail-on-empty")),
    Step("test-infra-policy", (PYTHON, "scripts/guards/check_test_infra_policy.py")),
    Step("namespace-doc", (PYTHON, "scripts/guards/gen_namespaces.py", "--check")),
    Step("tree-map", (PYTHON, "scripts/guards/gen_tree.py", "--check")),
    Step("structure-baseline", (PYTHON, "scripts/guards/gen_structure_baseline.py", "--check")),
    Step("graph", (PYTHON, "scripts/guards/gen_graph.py", "--check")),
    Step("mypy", ("uv", "run", "mypy")),
    Step("mypy-scope", (PYTHON, "scripts/guards/check_mypy_scope.py", "--fail-on-empty")),
    Step("prompt-surface", (PYTHON, "scripts/ci/prompt_surface.py", "--check")),
    Step("import-contracts", ("uv", "run", "lint-imports")),
    # serve 契约三守卫：codegen 漂移 / kind 覆盖 / 持久化版本（各自带自证用例）。
    Step("wire-codegen", (PYTHON, "-m", "pytest", "tests/ci/test_wire_codegen.py", "-q")),
    # TS 侧的同一份契约：schema → protocol/_gen/app-wire.ts，漂移即红。
    Step("wire-codegen-ts", ("node", "scripts/codegen/gen_wire_ts.mjs", "--check")),
    # 黄金帧：13 kind 各一例，构造器与冻结样本逐字段一致。
    Step("serve-wire-fixtures", (PYTHON, "-m", "pytest", "tests/ci/test_serve_wire_fixtures.py", "-q")),
    Step("kind-coverage", (PYTHON, "-m", "pytest", "tests/ci/test_kind_coverage.py", "-q")),
    Step(
        "persistence-version",
        (PYTHON, "-m", "pytest", "tests/ci/test_persistence_version.py", "-q"),
    ),
    Step("legacy-host-removed", (PYTHON, "-m", "pytest", "tests/ci/test_legacy_host_removed.py", "-q")),
    Step(
        "baseline-check",
        # 不传 --fast:pytest 收集计数与 node-id 集是这份基线存在的意义,
        # 传了 --fast 它们在 CI 里永远不生效,"删测试静默通过"就会回来。
        ("uv", "run", "python", "scripts/baseline_check.py", "--check"),
        slow=True,
    ),
)


def _run(step: Step) -> tuple[int, str, float]:
    started = time.perf_counter()
    try:
        result = subprocess.run(
            list(step.argv),
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError as exc:
        return 2, f"command not found: {exc}", time.perf_counter() - started
    output = (result.stdout + result.stderr).strip()
    return result.returncode, output, time.perf_counter() - started


def _tail(text: str, limit: int = 24) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-limit:])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fast", action="store_true", help="skip the slow snapshot checks (pre-commit)")
    parser.add_argument("--list", action="store_true", help="print the step table and exit")
    parser.add_argument("--verbose", action="store_true", help="always print each step's output")
    args = parser.parse_args(argv)

    if args.list:
        for step in STEPS:
            marker = "slow" if step.slow else "fast"
            print(f"  [{marker}] {step.name}: {' '.join(step.argv)}")
        return 0

    selected = [step for step in STEPS if not (args.fast and step.slow)]
    skipped = [step for step in STEPS if args.fast and step.slow]
    results: list[tuple[str, int, float]] = []
    failures: list[tuple[str, str]] = []
    total_started = time.perf_counter()

    for step in selected:
        print(f"-> {step.name}", flush=True)
        code, output, elapsed = _run(step)
        results.append((step.name, code, elapsed))
        if args.verbose or code != 0:
            if output:
                print(_tail(output), flush=True)
        if code != 0:
            failures.append((step.name, output))

    total = time.perf_counter() - total_started
    print("")
    print(f"{'step':<26}{'result':<10}{'seconds':>8}")
    for name, code, elapsed in results:
        status = "ok" if code == 0 else "FAILED"
        print(f"{name:<26}{status:<10}{elapsed:>8.2f}")
    for step in skipped:
        print(f"{step.name:<26}{'skipped':<10}{'-':>8}")
    print(f"{'total':<26}{'':<10}{total:>8.2f}")

    if failures:
        print("")
        print(f"check.py: {len(failures)} failed step(s): {', '.join(name for name, _ in failures)}")
        return 1
    print("")
    print(f"check.py: OK ({len(results)} steps, {total:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
