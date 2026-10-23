"""``RepoAutopilotStore`` mixin: gitops."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from questorharness.runtime.autopilot.text_utils import (
    _safe_text,
)
from questorharness.runtime.autopilot.types import (
    RepoTaskCard,
)


class GitOperationsMixin:
    """Gitops operations for the repo autopilot store."""

    def _max_attempts(self, policies: dict[str, Any]) -> int:
        execution = dict(policies.get("autopilot", {}).get("execution", {}))
        repair = dict(policies.get("autopilot", {}).get("repair", {}))
        execution_attempts = int(execution.get("max_attempts", 3) or 3)
        repair_rounds = int(repair.get("max_rounds", 2) or 2)
        return max(execution_attempts, repair_rounds + 1, 1)

    def _base_branch(self, policies: dict[str, Any]) -> str:
        execution = dict(policies.get("autopilot", {}).get("execution", {}))
        return _safe_text(execution.get("base_branch")) or "main"

    def _head_branch(self, card: RepoTaskCard, policies: dict[str, Any]) -> str:
        github_policy = dict(policies.get("autopilot", {}).get("github", {}))
        prefix = _safe_text(github_policy.get("pr_branch_prefix")) or "autopilot/"
        return f"{prefix}{card.id}"

    def _worktree_slug(self, card: RepoTaskCard) -> str:
        return f"autopilot/{card.id}"

    def _run_command(
        self,
        command: str | list[str],
        *,
        cwd: Path | None = None,
        timeout: int | None = None,
        shell: bool = False,
        check: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            command,
            cwd=cwd or self._cwd,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
            shell=shell,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": ""},
        )
        if check and completed.returncode != 0:
            output = (completed.stderr or completed.stdout).strip() or f"Command failed: {command}"
            raise RuntimeError(output)
        return completed

    def _run_git(self, args: list[str], *, cwd: Path | None = None, check: bool = False) -> subprocess.CompletedProcess[str]:
        return self._run_command(["git", *args], cwd=cwd, check=check)

    def _run_gh(self, args: list[str], *, cwd: Path | None = None, check: bool = False) -> subprocess.CompletedProcess[str]:
        return self._run_command(["gh", *args], cwd=cwd, check=check)

    def _gh_json(self, args: list[str], *, cwd: Path | None = None) -> Any:
        completed = self._run_gh(args, cwd=cwd, check=True)
        raw = (completed.stdout or "").strip()
        if not raw:
            return None
        return json.loads(raw)

    def _git_has_changes(self, cwd: Path) -> bool:
        completed = self._run_git(["status", "--porcelain"], cwd=cwd, check=True)
        return bool((completed.stdout or "").strip())

    def _is_git_repo(self, cwd: Path) -> bool:
        completed = self._run_git(["rev-parse", "--git-dir"], cwd=cwd)
        return completed.returncode == 0

    def _git_commit_all(self, cwd: Path, message: str) -> bool:
        if not self._git_has_changes(cwd):
            return False
        self._run_git(["add", "-A"], cwd=cwd, check=True)
        self._run_git(["commit", "-m", message], cwd=cwd, check=True)
        return True

    def _git_push_branch(self, cwd: Path, branch: str) -> None:
        self._run_git(["push", "-u", "origin", branch], cwd=cwd, check=True)

    def _git_branch_has_progress(self, cwd: Path, *, base_branch: str) -> bool:
        completed = self._run_git(
            ["rev-list", "--count", f"origin/{base_branch}..HEAD"],
            cwd=cwd,
        )
        if completed.returncode != 0:
            return False
        try:
            return int((completed.stdout or "0").strip() or "0") > 0
        except ValueError:
            return False

    def _sync_worktree_to_base(self, cwd: Path, *, base_branch: str, head_branch: str, reset: bool) -> None:
        self._run_git(["fetch", "origin", base_branch], cwd=cwd, check=True)
        if reset:
            self._run_git(["checkout", "-B", head_branch, f"origin/{base_branch}"], cwd=cwd, check=True)
            return
        self._run_git(["checkout", head_branch], cwd=cwd, check=True)
