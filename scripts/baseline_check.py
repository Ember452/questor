"""Reproducible Phase 2 baseline checker.

Records and verifies the six baseline items from docs/architecture/MIGRATION.md:

1. pytest pass set
2. collected node-id set (relative to main plus an explicit allow-list)
3. import-linter contracts
4. cold import
5. three CLI help outputs
6. dry-run (the ``- Git: yes (branch: ...)`` line is stripped)
7. session snapshot loads four messages
8. ``questor doctor`` output

Usage:
    uv run python scripts/baseline_check.py --record
    uv run python scripts/baseline_check.py --check
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_DIR = REPO_ROOT / "tests" / "fixtures" / "baseline"

ENV_PREFIXES = ("QUESTORHARNESS_",)
ENV_NAMES = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "DEEPSEEK_API_KEY",
)

PYTEST_MARK = "unit or integration"
HELP_COMMANDS = {
    "help-questor-module.txt": [sys.executable, "-m", "questor", "--help"],
    "help-questorharness.txt": ["questorharness", "--help"],
    "help-questor.txt": ["questor", "--help"],
}

SUMMARY_LINE = re.compile(r"^(\d+) passed, (\d+) skipped, (\d+) deselected")
LINT_LINE = re.compile(r"^Contracts: (\d+) kept, (\d+) broken\.")
MESSAGES_LINE = re.compile(r"^messages= (\d+)$", re.MULTILINE)
GIT_LINE = re.compile(r"^\s*-\s*Git:\s*yes \(branch:.*\)\s*$")

SNAPSHOT_SCRIPT = """
import os, shutil, tempfile
from pathlib import Path
root = Path(tempfile.mkdtemp(prefix="questor-snapshot-"))
os.environ["QUESTORHARNESS_DATA_DIR"] = str(root / "data")
from questorharness.contracts.session_storage import get_project_session_dir, load_session_snapshot
cwd = root / "baseline"
cwd.mkdir()
session_dir = get_project_session_dir(cwd)
shutil.copyfile("tests/fixtures/snapshots/session-snapshot-v0.json", session_dir / "latest.json")
snap = load_session_snapshot(cwd)
print(f"messages= {len(snap['messages'])}")
assert len(snap["messages"]) == 4
"""


def _child_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key not in ENV_NAMES}
    for key in list(env):
        if key.startswith(ENV_PREFIXES):
            env.pop(key)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _normalize(text: str) -> str:
    text = text.replace(str(REPO_ROOT), "<REPO>")
    text = text.replace(str(REPO_ROOT).replace("\\", "/"), "<REPO>")
    text = text.replace(str(Path.home()), "<HOME>")
    return text


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=REPO_ROOT,
        env=_child_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _uv(args: list[str]) -> subprocess.CompletedProcess[str]:
    return _run(["uv", "run", *args])


def _pytest_counts() -> tuple[dict[str, int], str]:
    result = _uv(["pytest", "-m", PYTEST_MARK, "-q"])
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    for line in reversed(lines):
        match = SUMMARY_LINE.match(line)
        if match:
            counts = {
                "passed": int(match.group(1)),
                "skipped": int(match.group(2)),
                "deselected": int(match.group(3)),
            }
            return counts, ""
    tail = "\n".join(lines[-15:])
    return {}, f"pytest summary not found (exit {result.returncode}):\n{tail}"


def _node_ids() -> tuple[list[str], str]:
    result = _uv(["pytest", "-m", PYTEST_MARK, "--collect-only", "-q"])
    ids = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip().startswith("tests/") and "::" in line
    ]
    if not ids:
        return [], f"no node ids collected (exit {result.returncode})"
    return sorted(set(ids)), ""


def _lint() -> tuple[dict[str, int], str]:
    result = _uv(["lint-imports"])
    output = result.stdout + result.stderr
    for line in output.splitlines():
        match = LINT_LINE.match(line.strip())
        if match:
            return {"kept": int(match.group(1)), "broken": int(match.group(2))}, ""
    return {}, f"lint summary not found (exit {result.returncode}):\n{output[-800:]}"


def _cold_import() -> tuple[int, str, str]:
    result = _uv(["python", "-c", "import questorharness; import questor"])
    output = (result.stdout + result.stderr).strip()
    return result.returncode, output, ""


def _snapshot() -> tuple[int, str]:
    result = _uv(["python", "-c", SNAPSHOT_SCRIPT])
    match = MESSAGES_LINE.search(result.stdout)
    if not match:
        detail = (result.stdout + result.stderr)[-1500:]
        return -1, f"snapshot check failed (exit {result.returncode}):\n{detail}"
    return int(match.group(1)), ""


def _collect_outputs() -> tuple[dict[str, object], list[str]]:
    errors: list[str] = []
    outputs: dict[str, object] = {}

    counts, error = _pytest_counts()
    if error:
        errors.append(error)
    outputs["pytest"] = counts

    node_ids, error = _node_ids()
    if error:
        errors.append(error)
    outputs["node_ids"] = node_ids

    lint, error = _lint()
    if error:
        errors.append(error)
    outputs["lint"] = lint

    cold_exit, cold_output, error = _cold_import()
    if error:
        errors.append(error)
    if cold_exit != 0 or cold_output:
        errors.append(f"cold import not clean: exit={cold_exit} output={cold_output!r}")
    outputs["cold_import"] = {"exit": cold_exit, "output": cold_output}

    messages, error = _snapshot()
    if error:
        errors.append(error)
    outputs["snapshot_messages"] = messages

    for name, command in HELP_COMMANDS.items():
        if command[0] == sys.executable:
            result = _uv(["python", *command[1:]])
        else:
            result = _run(["uv", "run", *command])
        text = _normalize(result.stdout + result.stderr)
        outputs[name] = text
        if result.returncode != 0:
            errors.append(f"{name} exited {result.returncode}")

    dry = _uv(["questorharness", "--dry-run"])
    dry_text = _normalize(dry.stdout + dry.stderr)
    dry_text = "\n".join(line for line in dry_text.splitlines() if not GIT_LINE.match(line))
    outputs["dryrun.txt"] = dry_text + ("\n" if dry_text else "")
    if dry.returncode != 0:
        errors.append(f"dry-run exited {dry.returncode}")

    doctor = _uv(["python", "-m", "questor", "doctor"])
    outputs["doctor.txt"] = _normalize(doctor.stdout + doctor.stderr)
    if doctor.returncode != 0:
        errors.append(f"doctor exited {doctor.returncode}")

    return outputs, errors


def _read_allowed() -> list[str]:
    path = BASELINE_DIR / "allowed_node_ids.txt"
    if not path.exists():
        return []
    return sorted(line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _write_text(name: str, text: str) -> None:
    (BASELINE_DIR / name).write_text(text, encoding="utf-8", newline="\n")


def record() -> int:
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    outputs, errors = _collect_outputs()
    if errors:
        print("record failed:")
        for error in errors:
            print(f"  - {error}")
        return 2

    node_ids: list[str] = outputs["node_ids"]  # type: ignore[assignment]
    allowed = _read_allowed()
    allowed_set = set(allowed)
    missing = sorted(allowed_set - set(node_ids))
    if missing:
        print("allowed node ids are not collected:")
        for item in missing:
            print(f"  - {item}")
        return 2

    main_ids = sorted(set(node_ids) - allowed_set)
    _write_text("main_node_ids.txt", "\n".join(main_ids) + "\n")

    for name in (
        "help-questor-module.txt",
        "help-questorharness.txt",
        "help-questor.txt",
        "dryrun.txt",
        "doctor.txt",
    ):
        _write_text(name, str(outputs[name]))

    summary = {
        "pytest": outputs["pytest"],
        "lint": outputs["lint"],
        "cold_import": outputs["cold_import"],
        "snapshot_messages": outputs["snapshot_messages"],
        "node_id_count": len(node_ids),
        "main_node_id_count": len(main_ids),
        "allowed_node_id_count": len(allowed),
    }
    _write_text("summary.json", json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(f"recorded baseline in {BASELINE_DIR.relative_to(REPO_ROOT)}")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _diff(name: str, expected: str, actual: str) -> list[str]:
    if expected == actual:
        return []
    diff = difflib.unified_diff(
        expected.splitlines(),
        actual.splitlines(),
        fromfile=f"baseline/{name}",
        tofile=f"current/{name}",
        lineterm="",
        n=2,
    )
    return [f"--- {name} differs ---", *list(diff)[:60]]


def check() -> int:
    if not (BASELINE_DIR / "summary.json").exists():
        print("no baseline recorded; run with --record first")
        return 2

    outputs, errors = _collect_outputs()
    failures: list[str] = list(errors)

    summary = json.loads((BASELINE_DIR / "summary.json").read_text(encoding="utf-8"))
    expected_counts = summary["pytest"]
    if outputs["pytest"] != expected_counts:
        failures.append(f"pytest counts changed: {expected_counts} -> {outputs['pytest']}")
    if outputs["lint"] != summary["lint"]:
        failures.append(f"lint changed: {summary['lint']} -> {outputs['lint']}")
    if outputs["cold_import"] != summary["cold_import"]:
        failures.append(f"cold import changed: {summary['cold_import']} -> {outputs['cold_import']}")
    if outputs["snapshot_messages"] != summary["snapshot_messages"]:
        failures.append(
            f"snapshot messages changed: {summary['snapshot_messages']} -> {outputs['snapshot_messages']}"
        )

    for name in (
        "help-questor-module.txt",
        "help-questorharness.txt",
        "help-questor.txt",
        "dryrun.txt",
        "doctor.txt",
    ):
        expected = (BASELINE_DIR / name).read_text(encoding="utf-8")
        failures.extend(_diff(name, expected, str(outputs[name])))

    allowed = set(_read_allowed())
    main_ids = set(
        line.strip()
        for line in (BASELINE_DIR / "main_node_ids.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    current = set(outputs["node_ids"])  # type: ignore[arg-type]
    added = sorted(current - main_ids)
    removed = sorted(main_ids - current)
    unexpected_added = sorted(set(added) - allowed)
    missing_allowed = sorted(allowed - current)
    if unexpected_added:
        failures.append("unexpected new node ids:\n  " + "\n  ".join(unexpected_added))
    if removed:
        failures.append("removed node ids:\n  " + "\n  ".join(removed))
    if missing_allowed:
        failures.append("allowed node ids missing:\n  " + "\n  ".join(missing_allowed))

    if failures:
        print("BASELINE CHECK FAILED")
        for failure in failures:
            print(failure)
        return 1

    print("BASELINE CHECK PASSED")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--record", action="store_true", help="record the current tree as baseline")
    group.add_argument("--check", action="store_true", help="compare the current tree to baseline")
    args = parser.parse_args()
    return record() if args.record else check()


if __name__ == "__main__":
    raise SystemExit(main())
