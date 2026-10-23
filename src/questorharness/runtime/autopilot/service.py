"""Project-level repo autopilot state, intake, and execution helpers."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from questorharness.platform.io import atomic_write_text
from questorharness.platform.paths import (
    get_project_active_repo_context_path,
    get_project_autopilot_registry_path,
    get_project_autopilot_runs_dir,
    get_project_repo_journal_path,
)
from questorharness.runtime.autopilot.dashboard import DashboardMixin
from questorharness.runtime.autopilot.github import GitHubOperationsMixin
from questorharness.runtime.autopilot.gitops import GitOperationsMixin
from questorharness.runtime.autopilot.sources import SourcesMixin
from questorharness.runtime.autopilot.storage import StorageMixin
from questorharness.runtime.autopilot.text_utils import (
    _safe_text,
    _shorten,
)
from questorharness.runtime.autopilot.types import (
    RepoRunResult,
    RepoTaskCard,
)
from questorharness.runtime.autopilot.verification import VerificationMixin
from questorharness.runtime.swarm.worktree import WorktreeManager


class RepoAutopilotStore(StorageMixin, SourcesMixin, GitOperationsMixin, GitHubOperationsMixin, VerificationMixin, DashboardMixin):
    """Persist and query project-level autopilot state."""

    def __init__(self, cwd: str | Path) -> None:
        self._cwd = Path(cwd).resolve()
        self._registry_path = get_project_autopilot_registry_path(self._cwd)
        self._journal_path = get_project_repo_journal_path(self._cwd)
        self._context_path = get_project_active_repo_context_path(self._cwd)
        self._runs_dir = get_project_autopilot_runs_dir(self._cwd)
        self._ensure_layout()

    @property
    def registry_path(self) -> Path:
        return self._registry_path

    @property
    def journal_path(self) -> Path:
        return self._journal_path

    @property
    def context_path(self) -> Path:
        return self._context_path

    @property
    def runs_dir(self) -> Path:
        return self._runs_dir


    async def run_next(
        self,
        *,
        model: str | None = None,
        max_turns: int | None = None,
        permission_mode: str | None = None,
    ) -> RepoRunResult:
        card = self.pick_next_card()
        if card is None:
            raise ValueError("No queued autopilot cards.")
        return await self.run_card(
            card.id,
            model=model,
            max_turns=max_turns,
            permission_mode=permission_mode,
        )

    async def run_card(
        self,
        card_id: str,
        *,
        model: str | None = None,
        max_turns: int | None = None,
        permission_mode: str | None = None,
    ) -> RepoRunResult:
        card = self.get_card(card_id)
        if card is None:
            raise ValueError(f"No autopilot card found with ID: {card_id}")
        if card.status in {"preparing", "running", "verifying", "waiting_ci", "repairing"}:
            raise ValueError(f"Autopilot card {card.id} is already active.")

        policies = self.load_policies()
        execution = dict(policies.get("autopilot", {}).get("execution", {}))
        effective_model = model or _safe_text(execution.get("default_model")) or None
        effective_max_turns = max_turns if max_turns is not None else int(execution.get("max_turns", 12))
        effective_permission_mode = permission_mode or _safe_text(
            execution.get("permission_mode", "full_auto")
        )
        max_attempts = self._max_attempts(policies)
        base_branch = self._base_branch(policies)
        head_branch = self._head_branch(card, policies)
        issue_number = self._issue_number_for_card(card)
        linked_pr_number = self._linked_pr_number(card)
        use_worktree = bool(execution.get("use_worktree", True)) and self._is_git_repo(self._cwd)

        if card.source_kind == "github_pr" and linked_pr_number is not None and not card.metadata.get("autopilot_managed"):
            return await self._process_existing_pr_card(card, linked_pr_number, policies)

        worktree_manager = WorktreeManager()
        worktree_info = None
        working_cwd = self._cwd
        if use_worktree:
            worktree_info = await worktree_manager.create_worktree(
                self._cwd,
                self._worktree_slug(card),
                branch=head_branch,
            )
            working_cwd = worktree_info.path
        existing_attempts = int(card.metadata.get("attempt_count", 0) or 0)
        self.update_status(
            card.id,
            status="preparing",
            note="preparing isolated worktree" if use_worktree else "preparing local execution",
            metadata_updates={
                "run_started_at": time.time(),
                "execution_model": effective_model or "",
                "max_attempts": max_attempts,
                "worktree_slug": self._worktree_slug(card),
                "worktree_path": str(working_cwd),
                "head_branch": head_branch,
                "base_branch": base_branch,
                "linked_issue_numbers": [issue_number] if issue_number is not None else [],
                "linked_pr_number": linked_pr_number,
            },
        )

        if issue_number is not None and existing_attempts == 0:
            self._comment_on_issue(issue_number, self._comment_started(card, existing_attempts + 1))

        current_run_report = self._runs_dir / f"{card.id}-run.md"
        current_verification_report = self._runs_dir / f"{card.id}-verification.md"
        prior_summary = _safe_text(card.metadata.get("assistant_summary_preview"))
        prior_failure_stage = _safe_text(card.metadata.get("last_failure_stage"))
        prior_failure_summary = _safe_text(card.metadata.get("last_failure_summary"))

        for attempt_count in range(existing_attempts + 1, max_attempts + 1):
            attempt_run_report = self._runs_dir / f"{card.id}-attempt-{attempt_count:02d}-run.md"
            attempt_verification_report = self._runs_dir / f"{card.id}-attempt-{attempt_count:02d}-verification.md"
            is_first_attempt = attempt_count == 1 and existing_attempts == 0
            if use_worktree:
                try:
                    self._sync_worktree_to_base(
                        working_cwd,
                        base_branch=base_branch,
                        head_branch=head_branch,
                        reset=is_first_attempt,
                    )
                except Exception as exc:
                    summary = f"Failed to prepare worktree branch: {exc}"
                    self.update_status(
                        card.id,
                        status="failed",
                        note=summary,
                        metadata_updates={"last_failure_stage": "git_prepare_failed", "last_failure_summary": summary},
                    )
                    self.append_journal(kind="run_failed", summary=summary, task_id=card.id)
                    return RepoRunResult(
                        card_id=card.id,
                        status="failed",
                        run_report_path=str(current_run_report),
                        verification_report_path=str(current_verification_report),
                        attempt_count=attempt_count,
                        worktree_path=str(working_cwd),
                    )

            self.update_status(
                card.id,
                status="repairing" if attempt_count > 1 else "running",
                note="repairing failed run" if attempt_count > 1 else "autopilot execution started",
                metadata_updates={"attempt_count": attempt_count},
            )
            prompt = self._prepare_repair_prompt(
                card,
                policies,
                attempt_count=attempt_count,
                prior_summary=prior_summary,
                failure_stage=prior_failure_stage,
                failure_summary=prior_failure_summary,
            )
            try:
                assistant_summary = await self._run_agent_prompt(
                    prompt,
                    model=effective_model,
                    max_turns=effective_max_turns,
                    permission_mode=effective_permission_mode,
                    cwd=working_cwd,
                )
            except Exception as exc:
                failure_text = self._render_run_report(
                    card,
                    agent_summary=f"Autopilot execution failed: {exc}",
                    verification_steps=[],
                    verification_status="not_started",
                )
                for path in (attempt_run_report, current_run_report):
                    atomic_write_text(path, failure_text)
                summary = f"agent execution failed: {exc}"
                self.update_status(
                    card.id,
                    status="failed",
                    note=summary,
                    metadata_updates={
                        "execution_error": str(exc),
                        "last_failure_stage": "agent_runtime_error",
                        "last_failure_summary": summary,
                    },
                )
                self.append_journal(
                    kind="run_failed",
                    summary=f"{card.title}: agent execution failed",
                    task_id=card.id,
                    metadata={"error": str(exc), "attempt_count": attempt_count},
                )
                if issue_number is not None:
                    self._comment_on_issue(issue_number, self._comment_terminal_failure(summary))
                return RepoRunResult(
                    card_id=card.id,
                    status="failed",
                    assistant_summary=failure_text.strip(),
                    run_report_path=str(current_run_report),
                    verification_report_path=str(current_verification_report),
                    verification_steps=[],
                    attempt_count=attempt_count,
                    worktree_path=str(working_cwd),
                )

            pending_report = self._render_run_report(
                card,
                agent_summary=assistant_summary,
                verification_steps=[],
                verification_status="pending",
            )
            for path in (attempt_run_report, current_run_report):
                atomic_write_text(path, pending_report)
            self.append_journal(
                kind="run_finished",
                summary=f"Agent run finished for {card.title}",
                task_id=card.id,
                metadata={"run_report_path": str(attempt_run_report), "attempt_count": attempt_count},
            )

            self.update_status(
                card.id,
                status="verifying",
                note="running verification gates",
                metadata_updates={"assistant_summary_preview": _shorten(assistant_summary, limit=300)},
            )
            verification_steps = self._run_verification_steps(policies, cwd=working_cwd)
            verification_text = self._render_verification_report(card, verification_steps)
            for path in (attempt_verification_report, current_verification_report):
                atomic_write_text(path, verification_text)

            failing = [step for step in verification_steps if step.status in {"failed", "error"}]
            final_local_report = self._render_run_report(
                card,
                agent_summary=assistant_summary,
                verification_steps=verification_steps,
                verification_status="failed" if failing else "passed",
            )
            for path in (attempt_run_report, current_run_report):
                atomic_write_text(path, final_local_report)
            prior_summary = assistant_summary

            if failing:
                summary = "; ".join(f"{step.command} rc={step.returncode}" for step in failing[:3])
                metadata_updates = {
                    "verification_failed": True,
                    "verification_steps": [step.model_dump(mode="json") for step in verification_steps],
                    "last_failure_stage": "local_verification_failed",
                    "last_failure_summary": summary,
                }
                if attempt_count < max_attempts:
                    self.update_status(
                        card.id,
                        status="repairing",
                        note="local verification failed; retrying",
                        metadata_updates=metadata_updates,
                    )
                    self.append_journal(
                        kind="verification_failed",
                        summary=f"{card.title}: local verification failed, retrying",
                        task_id=card.id,
                        metadata={"attempt_count": attempt_count},
                    )
                    if issue_number is not None:
                        self._comment_on_issue(issue_number, self._comment_local_failed(attempt_count, summary))
                    prior_failure_stage = "local_verification_failed"
                    prior_failure_summary = summary
                    continue

                self.update_status(
                    card.id,
                    status="failed",
                    note=f"{len(failing)} verification gate(s) failed",
                    metadata_updates=metadata_updates,
                )
                self.append_journal(
                    kind="verification_failed",
                    summary=f"{card.title}: {len(failing)} verification gate(s) failed",
                    task_id=card.id,
                )
                if issue_number is not None:
                    self._comment_on_issue(issue_number, self._comment_terminal_failure(summary))
                return RepoRunResult(
                    card_id=card.id,
                    status="failed",
                    assistant_summary=assistant_summary,
                    run_report_path=str(current_run_report),
                    verification_report_path=str(current_verification_report),
                    verification_steps=verification_steps,
                    attempt_count=attempt_count,
                    worktree_path=str(working_cwd),
                )

            if not self._is_git_repo(working_cwd):
                self.update_status(
                    card.id,
                    status="completed",
                    note="local verification passed; repository is not a git repo so GitHub automation was skipped",
                    metadata_updates={
                        "verification_failed": False,
                        "verification_steps": [step.model_dump(mode="json") for step in verification_steps],
                        "human_gate_pending": True,
                    },
                )
                return RepoRunResult(
                    card_id=card.id,
                    status="completed",
                    assistant_summary=assistant_summary,
                    run_report_path=str(current_run_report),
                    verification_report_path=str(current_verification_report),
                    verification_steps=verification_steps,
                    attempt_count=attempt_count,
                    worktree_path=str(working_cwd),
                )

            commit_created = self._git_commit_all(
                working_cwd,
                f"autopilot({card.id}): {card.title}",
            )
            branch_has_progress = commit_created or self._git_branch_has_progress(
                working_cwd,
                base_branch=base_branch,
            )
            if not branch_has_progress:
                no_changes_summary = "Agent produced no code changes to commit."
                if attempt_count < max_attempts:
                    self.update_status(
                        card.id,
                        status="repairing",
                        note="agent produced no changes; retrying",
                        metadata_updates={
                            "last_failure_stage": "no_changes",
                            "last_failure_summary": no_changes_summary,
                        },
                    )
                    prior_failure_stage = "no_changes"
                    prior_failure_summary = no_changes_summary
                    continue
                self.update_status(
                    card.id,
                    status="failed",
                    note=no_changes_summary,
                    metadata_updates={
                        "last_failure_stage": "no_changes",
                        "last_failure_summary": no_changes_summary,
                    },
                )
                return RepoRunResult(
                    card_id=card.id,
                    status="failed",
                    assistant_summary=assistant_summary,
                    run_report_path=str(current_run_report),
                    verification_report_path=str(current_verification_report),
                    verification_steps=verification_steps,
                    attempt_count=attempt_count,
                    worktree_path=str(working_cwd),
                )
            if not commit_created:
                self.append_journal(
                    kind="existing_progress_detected",
                    summary=f"{card.title}: reusing existing local branch progress",
                    task_id=card.id,
                    metadata={"attempt_count": attempt_count, "head_branch": head_branch},
                )

            try:
                self._git_push_branch(working_cwd, head_branch)
                pr_info = self._upsert_pull_request(
                    card,
                    head_branch=head_branch,
                    base_branch=base_branch,
                    run_report_path=current_run_report,
                    verification_report_path=current_verification_report,
                )
            except Exception as exc:
                summary = f"Failed to push branch or upsert PR: {exc}"
                self.update_status(
                    card.id,
                    status="failed",
                    note=summary,
                    metadata_updates={"last_failure_stage": "github_pr_open_failed", "last_failure_summary": summary},
                )
                if issue_number is not None:
                    self._comment_on_issue(issue_number, self._comment_terminal_failure(summary))
                return RepoRunResult(
                    card_id=card.id,
                    status="failed",
                    assistant_summary=assistant_summary,
                    run_report_path=str(current_run_report),
                    verification_report_path=str(current_verification_report),
                    verification_steps=verification_steps,
                    attempt_count=attempt_count,
                    worktree_path=str(worktree_info.path),
                )

            linked_pr_number = int(pr_info.get("number"))
            pr_url = _safe_text(pr_info.get("url"))
            self.update_status(
                card.id,
                status="waiting_ci",
                note=f"waiting for remote CI on PR #{linked_pr_number}",
                metadata_updates={
                    "linked_pr_number": linked_pr_number,
                    "linked_pr_url": pr_url,
                    "linked_issue_numbers": [issue_number] if issue_number is not None else [],
                    "autopilot_managed": True,
                    "verification_failed": False,
                    "verification_steps": [step.model_dump(mode="json") for step in verification_steps],
                },
            )
            self._comment_on_pr(linked_pr_number, self._comment_pr_opened(linked_pr_number, pr_url))

            ci_state, ci_summary, pr_snapshot, checks = await self._wait_for_pr_ci(linked_pr_number, policies)
            self.update_status(
                card.id,
                status="waiting_ci" if ci_state == "pending" else "waiting_ci",
                note=f"remote CI status: {ci_state}",
                metadata_updates={
                    "last_ci_conclusion": ci_state,
                    "last_ci_summary": ci_summary,
                    "last_ci_checks": checks,
                    "linked_pr_number": linked_pr_number,
                    "linked_pr_url": _safe_text(pr_snapshot.get("url")) or pr_url,
                },
            )
            if ci_state == "failed":
                if attempt_count < max_attempts:
                    self.update_status(
                        card.id,
                        status="repairing",
                        note="remote CI failed; retrying",
                        metadata_updates={
                            "last_failure_stage": "remote_ci_failed",
                            "last_failure_summary": ci_summary,
                        },
                    )
                    self.append_journal(
                        kind="ci_failed_retry",
                        summary=f"{card.title}: remote CI failed, retrying",
                        task_id=card.id,
                        metadata={"pr_number": linked_pr_number, "attempt_count": attempt_count},
                    )
                    self._comment_on_pr(linked_pr_number, self._comment_ci_failed(attempt_count, ci_summary))
                    prior_failure_stage = "remote_ci_failed"
                    prior_failure_summary = ci_summary
                    continue

                self.update_status(
                    card.id,
                    status="failed",
                    note=f"remote CI failed: {ci_summary}",
                    metadata_updates={
                        "last_failure_stage": "remote_ci_failed",
                        "last_failure_summary": ci_summary,
                    },
                )
                self._comment_on_pr(linked_pr_number, self._comment_terminal_failure(ci_summary))
                if issue_number is not None:
                    self._comment_on_issue(issue_number, self._comment_terminal_failure(ci_summary))
                return RepoRunResult(
                    card_id=card.id,
                    status="failed",
                    assistant_summary=assistant_summary,
                    run_report_path=str(current_run_report),
                    verification_report_path=str(current_verification_report),
                    verification_steps=verification_steps,
                    attempt_count=attempt_count,
                    worktree_path=str(working_cwd),
                    pr_number=linked_pr_number,
                    pr_url=pr_url,
                )

            if self._automerge_eligible(pr_snapshot, policies):
                self._merge_pull_request(linked_pr_number)
                self.update_status(
                    card.id,
                    status="merged",
                    note=f"PR #{linked_pr_number} merged automatically",
                    metadata_updates={"human_gate_pending": False},
                )
                self.append_journal(
                    kind="merged",
                    summary=f"{card.title}: PR #{linked_pr_number} merged",
                    task_id=card.id,
                    metadata={"pr_number": linked_pr_number},
                )
                self._comment_on_pr(linked_pr_number, self._comment_merged(linked_pr_number))
                if issue_number is not None:
                    self._comment_on_issue(issue_number, self._comment_merged(linked_pr_number))
                if use_worktree:
                    await worktree_manager.remove_worktree(self._worktree_slug(card))
                return RepoRunResult(
                    card_id=card.id,
                    status="merged",
                    assistant_summary=assistant_summary,
                    run_report_path=str(current_run_report),
                    verification_report_path=str(current_verification_report),
                    verification_steps=verification_steps,
                    attempt_count=attempt_count,
                    worktree_path=str(working_cwd),
                    pr_number=linked_pr_number,
                    pr_url=pr_url,
                )

            self.update_status(
                card.id,
                status="completed",
                note=f"PR #{linked_pr_number} is green; human gate pending",
                metadata_updates={
                    "human_gate_pending": True,
                    "linked_pr_number": linked_pr_number,
                    "linked_pr_url": pr_url,
                },
            )
            self.append_journal(
                kind="human_gate_pending",
                summary=f"{card.title}: PR #{linked_pr_number} is ready for human gate",
                task_id=card.id,
                metadata={"pr_number": linked_pr_number},
            )
            self._comment_on_pr(linked_pr_number, self._comment_human_gate(linked_pr_number))
            if issue_number is not None:
                self._comment_on_issue(issue_number, self._comment_human_gate(linked_pr_number))
            if use_worktree:
                await worktree_manager.remove_worktree(self._worktree_slug(card))
            return RepoRunResult(
                card_id=card.id,
                status="completed",
                assistant_summary=assistant_summary,
                run_report_path=str(current_run_report),
                verification_report_path=str(current_verification_report),
                verification_steps=verification_steps,
                attempt_count=attempt_count,
                worktree_path=str(working_cwd),
                pr_number=linked_pr_number,
                pr_url=pr_url,
            )

        exhausted = "repair rounds exhausted"
        self.update_status(
            card.id,
            status="failed",
            note=exhausted,
            metadata_updates={"last_failure_stage": "repair_exhausted", "last_failure_summary": exhausted},
        )
        return RepoRunResult(
            card_id=card.id,
            status="failed",
            run_report_path=str(current_run_report),
            verification_report_path=str(current_verification_report),
            attempt_count=max_attempts,
            worktree_path=str(working_cwd),
        )

    async def tick(
        self,
        *,
        model: str | None = None,
        max_turns: int | None = None,
        permission_mode: str | None = None,
        issue_limit: int = 10,
        pr_limit: int = 10,
    ) -> RepoRunResult | None:
        self.scan_all_sources(issue_limit=issue_limit, pr_limit=pr_limit)
        if any(card.status in {"preparing", "running", "verifying", "waiting_ci", "repairing"} for card in self.list_cards()):
            self.append_journal(kind="tick_skip", summary="Skipped run-next because another card is active")
            return None
        if self.pick_next_card() is None:
            self.append_journal(kind="tick_idle", summary="Tick completed with no queued work")
            return None
        return await self.run_next(
            model=model,
            max_turns=max_turns,
            permission_mode=permission_mode,
        )

    def install_default_cron(self) -> list[str]:
        from questorharness.capabilities.schedule.cron import upsert_cron_job

        jobs = [
            {
                "name": "autopilot.scan",
                "schedule": "*/30 * * * *",
                "command": f"oh autopilot scan all --cwd {self._cwd}",
                "cwd": str(self._cwd),
            },
            {
                "name": "autopilot.tick",
                "schedule": "0 */2 * * *",
                "command": f"oh autopilot tick --cwd {self._cwd}",
                "cwd": str(self._cwd),
            },
        ]
        for job in jobs:
            upsert_cron_job(job)
        return [job["name"] for job in jobs]


    async def _process_existing_pr_card(
        self,
        card: RepoTaskCard,
        pr_number: int,
        policies: dict[str, Any],
    ) -> RepoRunResult:
        current_run_report = self._runs_dir / f"{card.id}-run.md"
        current_verification_report = self._runs_dir / f"{card.id}-verification.md"
        self.update_status(
            card.id,
            status="waiting_ci",
            note=f"monitoring existing PR #{pr_number}",
            metadata_updates={"linked_pr_number": pr_number},
        )
        ci_state, ci_summary, pr_snapshot, _checks = await self._wait_for_pr_ci(pr_number, policies)
        pr_url = _safe_text(pr_snapshot.get("url"))
        if ci_state == "failed":
            self.update_status(
                card.id,
                status="failed",
                note=f"existing PR CI failed: {ci_summary}",
                metadata_updates={
                    "linked_pr_number": pr_number,
                    "linked_pr_url": pr_url,
                    "last_failure_stage": "remote_ci_failed",
                    "last_failure_summary": ci_summary,
                },
            )
            self._comment_on_pr(pr_number, self._comment_terminal_failure(ci_summary))
            return RepoRunResult(
                card_id=card.id,
                status="failed",
                run_report_path=str(current_run_report),
                verification_report_path=str(current_verification_report),
                pr_number=pr_number,
                pr_url=pr_url,
            )
        if self._automerge_eligible(pr_snapshot, policies):
            self._merge_pull_request(pr_number)
            self.update_status(
                card.id,
                status="merged",
                note=f"existing PR #{pr_number} merged automatically",
                metadata_updates={"linked_pr_number": pr_number, "linked_pr_url": pr_url},
            )
            self._comment_on_pr(pr_number, self._comment_merged(pr_number))
            return RepoRunResult(
                card_id=card.id,
                status="merged",
                run_report_path=str(current_run_report),
                verification_report_path=str(current_verification_report),
                pr_number=pr_number,
                pr_url=pr_url,
            )
        self.update_status(
            card.id,
            status="completed",
            note=f"existing PR #{pr_number} is green; human gate pending",
            metadata_updates={
                "linked_pr_number": pr_number,
                "linked_pr_url": pr_url,
                "human_gate_pending": True,
            },
        )
        self._comment_on_pr(pr_number, self._comment_human_gate(pr_number))
        return RepoRunResult(
            card_id=card.id,
            status="completed",
            run_report_path=str(current_run_report),
            verification_report_path=str(current_verification_report),
            pr_number=pr_number,
            pr_url=pr_url,
        )

# questor: allow R3 -- until W9 rename wave
# questor: allow R7 -- until W8 adds the mirror test
# questor: allow R8 -- refactor the offenders in W8
