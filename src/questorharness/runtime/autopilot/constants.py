"""Policy defaults and parsing helpers for the repo autopilot."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path

from questorharness.runtime.autopilot.types import RepoTaskSource

_SOURCE_BASE_SCORES: dict[RepoTaskSource, int] = {
    "questor_request": 100,
    "manual_idea": 80,
    "github_issue": 75,
    "github_pr": 85,
    "claude_code_candidate": 45,
}

_BUG_HINTS = ("bug", "fix", "failure", "broken", "regression", "crash", "error", "issue")

_URGENT_HINTS = ("urgent", "p0", "p1", "high", "critical", "blocker")

_DEFAULT_AUTOPILOT_POLICY = {
    "intake": {
        "mode": "unified_queue",
        "max_visible_candidates": 12,
        "dedupe_strategy": "source_ref_then_fingerprint",
    },
    "decision": {
        "default_human_gate": True,
        "prefer_small_safe_steps": True,
    },
    "execution": {
        "default_model": "",
        "max_turns": 12,
        "permission_mode": "full_auto",
        "host_mode": "self_hosted",
        "use_worktree": True,
        "base_branch": "main",
        "max_attempts": 3,
    },
    "github": {
        "issue_comment_style": "bilingual",
        "pr_branch_prefix": "autopilot/",
        "ci_poll_interval_seconds": 20,
        "ci_timeout_seconds": 1800,
        "no_checks_grace_seconds": 60,
        "checks_settle_seconds": 20,
        "auto_merge": {
            "mode": "label_gated",
            "required_label": "autopilot:merge",
        },
    },
    "repair": {
        "max_rounds": 2,
        "retry_on": ["local_verification_failed", "remote_ci_failed"],
        "stop_on": ["agent_runtime_error", "git_error", "permission_error", "merge_conflict"],
    },
}

_DEFAULT_VERIFICATION_POLICY = {
    "gates": [
        "fast_gate",
        "repo_gate",
        "harness_gate",
    ],
    "commands": [
        "uv run pytest -q",
        "uv run ruff check src tests scripts",
        {
            "command": (
                "cd frontend/terminal && "
                "([ -x ./node_modules/.bin/tsc ] || npm ci --no-audit --no-fund) && "
                "./node_modules/.bin/tsc --noEmit"
            ),
            "shell": True,
        },
    ],
    "require_tests_before_merge": True,
}

_DEFAULT_RELEASE_POLICY = {
    "merge_requires_human": True,
    "release_requires_human": True,
    "auto_revert_on_failed_verification": False,
}

_SHELL_METACHARS = frozenset(";&|`$<>\n\r")

@dataclass(frozen=True)
class _VerificationCommand:
    """Parsed verification-policy entry.

    When ``shell`` is false, ``argv`` is executed with ``shell=False``.
    When ``shell`` is true, ``raw`` is handed to the shell (explicit opt-in).
    ``error`` signals a policy entry that must not be executed; callers emit
    an error step so the verification gate fails loudly.
    """

    raw: str
    argv: tuple[str, ...]
    shell: bool
    error: str | None = None

def _parse_verification_entry(entry: object) -> _VerificationCommand:
    if isinstance(entry, dict):
        raw = str(entry.get("command", "")).strip()
        if not raw:
            return _VerificationCommand(raw=str(entry), argv=(), shell=False, error="empty command")
        if bool(entry.get("shell", False)):
            return _VerificationCommand(raw=raw, argv=(), shell=True)
        # 继续按 argv 形式校验命令
    elif isinstance(entry, str):
        raw = entry.strip()
        if not raw:
            return _VerificationCommand(raw=entry, argv=(), shell=False, error="empty command")
    else:
        return _VerificationCommand(
            raw=str(entry),
            argv=(),
            shell=False,
            error="entry must be a string or a mapping with a 'command' key",
        )

    if any(ch in _SHELL_METACHARS for ch in raw):
        return _VerificationCommand(
            raw=raw,
            argv=(),
            shell=False,
            error=(
                "command contains shell metacharacters; use the mapping form "
                "{command: '...', shell: true} in verification_policy.yaml to opt in"
            ),
        )
    try:
        argv = shlex.split(raw)
    except ValueError as exc:
        return _VerificationCommand(
            raw=raw,
            argv=(),
            shell=False,
            error=f"could not tokenize command: {exc}",
        )
    if not argv:
        return _VerificationCommand(raw=raw, argv=(), shell=False, error="empty command")
    return _VerificationCommand(raw=raw, argv=tuple(argv), shell=False)

def _looks_available(command: str, cwd: Path) -> bool:
    lowered = command.lower()
    if lowered.startswith("uv "):
        return (cwd / "pyproject.toml").exists()
    if "ruff check" in lowered:
        return (cwd / "pyproject.toml").exists()
    if "pytest" in lowered:
        return (cwd / "tests").exists()
    if "tsc" in lowered or "frontend/terminal" in lowered:
        return (cwd / "frontend" / "terminal" / "package.json").exists()
    return True

def _source_ref_number(source_ref: str, prefix: str) -> int | None:
    normalized = source_ref.strip()
    if not normalized.startswith(f"{prefix}:"):
        return None
    try:
        return int(normalized.split(":", 1)[1])
    except ValueError:
        return None
