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

# rich 控制台的渲染宽度;typer 经 ``TERMINAL_WIDTH`` 读到它。见 ``_child_env``。
RENDER_WIDTH = "80"
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_BOX_CORNERS = str.maketrans({"╭": "┌", "╮": "┐", "╰": "└", "╯": "┘"})
_VERTICAL_BORDERS = ("│", "┃")

SNAPSHOT_SCRIPT = """
import os, shutil, tempfile
from pathlib import Path
root = Path(tempfile.mkdtemp(prefix="questor-snapshot-"))
os.environ["QUESTORHARNESS_DATA_DIR"] = str(root / "data")
from questorharness.platform.session_storage import get_project_session_dir, load_session_snapshot
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
    # typer 把 ``TERMINAL_WIDTH`` 当作 rich 控制台的显式宽度(rich_utils.MAX_WIDTH)。
    # 不钉住时宽度取自终端:legacy Windows 控制台取的是终端宽减一(79),Linux runner
    # 取 80,于是每个面板的换行点和右侧补白整块漂一格。钉成 80,两边同宽。
    env["TERMINAL_WIDTH"] = RENDER_WIDTH
    return env


def _normalize(text: str) -> str:
    text = text.replace(str(REPO_ROOT), "<REPO>")
    text = text.replace(str(REPO_ROOT).replace("\\", "/"), "<REPO>")
    text = text.replace(str(Path.home()), "<HOME>")
    # ``- system prompt chars: N`` is len(system_prompt). That number embeds the
    # working directory, the date, the python path, the venv and the git branch,
    # so it changes when you switch branches and can never match across machines.
    # Pin its presence, not its value: prompt content is covered by
    # scripts/ci/prompt_surface.py with fixed rendering inputs.
    text = re.sub(r"(?m)^- system prompt chars: \d+$", "- system prompt chars: <VOLATILE>", text)
    # rich 在 legacy Windows 控制台上把圆角框降级成方角(box 的 safe 替换),Linux
    # 保持圆角:同一份 help 文本在两台机器上的角字符天然不同。只统一字形,不动内容。
    # ANSI 同理:typer 在 GITHUB_ACTIONS 下强制终端(rich_utils.FORCE_TERMINAL),
    # 本机管道不强制,颜色转义不该进入快照。
    text = _ANSI_ESCAPE.sub("", text).translate(_BOX_CORNERS)
    # 含掩码的行是机器路径行:整行统一分隔符,Windows 的 ``\\`` 与 Linux 的
    # ``/`` 不再造成假差异;不含掩码的正文一字不动。prompt_surface 也经由
    # 本函数获得同一口径。
    #
    # 掩码换掉的是长度不同的真实路径(checkout 路径 31 格,CI 的 33 格),rich
    # 面板右侧的补白因此跟着漂:含掩码的行去掉行尾竖线再 rstrip,内容照旧比对,
    # 纯补白不参与。
    trailing_newline = text.endswith("\n")
    lines = []
    for line in text.splitlines():
        if "<REPO>" not in line and "<HOME>" not in line:
            lines.append(line)
            continue
        line = line.replace("\\", "/")
        if line.endswith(_VERTICAL_BORDERS):
            line = line[:-1]
        lines.append(line.rstrip())
    text = "\n".join(lines) + ("\n" if trailing_newline else "")
    return text


def _scratch_env(name: str) -> dict[str, str]:
    """Build a child environment pinned to a one-shot scratch home.

    doctor 与 dry-run 的本职是反映真实环境,而基线要的是**确定的 环境**:
    不钉住的话,输出随机器漂移——本机已配置的认证在 CI 上是 missing auth,
    skill 发现会数到 ``~/.agents/skills`` 里装的每一个技能(基线曾因此带上
    42 个只有这台机器有的条目)。HOME/USERPROFILE、config、data 全部指向
    ``.tmp-baseline/<name>`` 下的一次性目录,两边渲染的都是"全新装机"视图。

    注意:HOME 被重定向后**不能再用 ``uv run``**(uv 依赖家目录缓存),调用方
    必须用 ``sys.executable -m ...`` 直跑 venv 解释器。
    """
    import shutil as _shutil

    scratch = REPO_ROOT / ".tmp-baseline" / name
    if scratch.exists():
        _shutil.rmtree(scratch)
    for sub in ("home", "data", "config"):
        (scratch / sub).mkdir(parents=True)
    env = _child_env()
    env["HOME"] = str(scratch / "home")
    env["USERPROFILE"] = str(scratch / "home")
    env["QUESTORHARNESS_DATA_DIR"] = str(scratch / "data")
    env["QUESTORHARNESS_CONFIG_DIR"] = str(scratch / "config")
    return env


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


def _collect_outputs(*, fast: bool = False) -> tuple[dict[str, object], list[str]]:
    errors: list[str] = []
    outputs: dict[str, object] = {}

    if not fast:
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

    dry = subprocess.run(
        [sys.executable, "-m", "questorharness", "--dry-run"],
        cwd=REPO_ROOT,
        env=_scratch_env("dryrun-env"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    dry_text = _normalize(dry.stdout + dry.stderr)
    dry_text = "\n".join(line for line in dry_text.splitlines() if not GIT_LINE.match(line))
    outputs["dryrun.txt"] = dry_text + ("\n" if dry_text else "")
    if dry.returncode != 0:
        errors.append(f"dry-run exited {dry.returncode}")

    doctor = subprocess.run(
        [sys.executable, "-m", "questor", "doctor"],
        cwd=REPO_ROOT,
        env=_scratch_env("doctor-env"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
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


def check(*, fast: bool = False) -> int:
    if not (BASELINE_DIR / "summary.json").exists():
        print("no baseline recorded; run with --record first")
        return 2

    outputs, errors = _collect_outputs(fast=fast)
    failures: list[str] = list(errors)

    summary = json.loads((BASELINE_DIR / "summary.json").read_text(encoding="utf-8"))
    if not fast:
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
    if not fast:
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
    parser.add_argument(
        "--fast",
        action="store_true",
        help="skip the pytest and node-id checks (CI guard mode)",
    )
    args = parser.parse_args()
    if args.fast and args.record:
        parser.error("--fast cannot be combined with --record")
    return check(fast=args.fast) if args.check else record()


if __name__ == "__main__":
    raise SystemExit(main())
