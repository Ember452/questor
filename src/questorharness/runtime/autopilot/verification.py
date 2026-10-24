"""``RepoAutopilotStore`` mixin: verification."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import yaml

from questorharness.runtime.autopilot.verification_defaults import (
    _looks_available,
    _parse_verification_entry,
    _VerificationCommand,
)
from questorharness.runtime.autopilot.runner import get_runtime_runner
from questorharness.runtime.autopilot.text_utils import (
    _safe_text,
    _shorten,
)
from questorharness.runtime.autopilot.models import (
    RepoTaskCard,
    RepoVerificationStep,
)


class VerificationMixin:
    """Verification operations for the repo autopilot store."""

    def _prepare_repair_prompt(
        self,
        card: RepoTaskCard,
        policies: dict[str, Any],
        *,
        attempt_count: int,
        prior_summary: str | None,
        failure_stage: str | None,
        failure_summary: str | None,
    ) -> str:
        prompt = self._build_execution_prompt(card, policies)
        if attempt_count <= 1 or not failure_stage:
            return prompt
        extras = [
            "",
            "Repair context:",
            f"- Attempt: {attempt_count}",
            f"- Previous failure stage: {failure_stage}",
            f"- Previous failure summary: {failure_summary or '(none)'}",
        ]
        if prior_summary:
            extras.append(f"- Previous agent summary: {_shorten(prior_summary, limit=600)}")
        extras.extend(
            [
                "",
                "Repair instructions:",
                "- Make the smallest patch that fixes the reported failure.",
                "- Do not restart the task from scratch if the existing branch already contains valid progress.",
                "- Re-run the relevant verification commands after the fix.",
            ]
        )
        return prompt + "\n" + "\n".join(extras).strip() + "\n"

    def _build_execution_prompt(self, card: RepoTaskCard, policies: dict[str, Any]) -> str:
        autopilot_policy = yaml.safe_dump(policies["autopilot"], sort_keys=False).strip()
        verification_policy = yaml.safe_dump(policies["verification"], sort_keys=False).strip()
        release_policy = yaml.safe_dump(policies["release"], sort_keys=False).strip()
        return (
            "You are executing one repo-autopilot task for the current repository.\n\n"
            "Goal:\n"
            "- Make the smallest coherent implementation that resolves the task.\n"
            "- Run the relevant verification commands yourself before stopping.\n"
            "- Do not merge, release, or perform irreversible external actions.\n"
            "- Leave the repository in a reviewable state and summarize what changed.\n\n"
            f"Task ID: {card.id}\n"
            f"Source: {card.source_kind}\n"
            f"Source ref: {card.source_ref or '-'}\n"
            f"Title: {card.title}\n"
            f"Body:\n{card.body or '(none)'}\n\n"
            "Autopilot policy:\n"
            f"{autopilot_policy}\n\n"
            "Verification policy:\n"
            f"{verification_policy}\n\n"
            "Release policy:\n"
            f"{release_policy}\n\n"
            "Expected output:\n"
            "1. What you changed.\n"
            "2. What you verified.\n"
            "3. Any remaining risk or human follow-up.\n"
        )

    async def _run_agent_prompt(
        self,
        prompt: str,
        *,
        model: str | None,
        max_turns: int,
        permission_mode: str,
        cwd: Path | None = None,
    ) -> str:
        runner = get_runtime_runner()
        if runner is None:
            raise RuntimeError("autopilot runtime runner is not configured")
        return await runner(
            prompt,
            model=model,
            max_turns=max_turns,
            permission_mode=permission_mode,
            cwd=cwd or self._cwd,
        )

    def _verification_commands(self, policies: dict[str, Any]) -> list[_VerificationCommand]:
        configured = policies.get("verification", {}).get("commands", [])
        parsed = [_parse_verification_entry(entry) for entry in configured]
        selected: list[_VerificationCommand] = []
        for cmd in parsed:
            if cmd.error is not None:
                selected.append(cmd)
                continue
            if _looks_available(cmd.raw, self._cwd):
                selected.append(cmd)
        return selected

    def _run_verification_steps(self, policies: dict[str, Any], *, cwd: Path | None = None) -> list[RepoVerificationStep]:
        steps: list[RepoVerificationStep] = []
        for cmd in self._verification_commands(policies):
            if cmd.error is not None:
                steps.append(
                    RepoVerificationStep(
                        command=cmd.raw,
                        returncode=-1,
                        status="error",
                        stderr=f"verification policy error: {cmd.error}",
                    )
                )
                continue
            target: str | list[str] = cmd.raw if cmd.shell else list(cmd.argv)
            try:
                completed = subprocess.run(
                    target,
                    cwd=cwd or self._cwd,
                    shell=cmd.shell,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=1800,
                )
                steps.append(
                    RepoVerificationStep(
                        command=cmd.raw,
                        returncode=completed.returncode,
                        status="success" if completed.returncode == 0 else "failed",
                        stdout=(completed.stdout or "")[-4000:],
                        stderr=(completed.stderr or "")[-4000:],
                    )
                )
            except FileNotFoundError as exc:
                steps.append(
                    RepoVerificationStep(
                        command=cmd.raw,
                        returncode=-1,
                        status="error",
                        stderr=f"executable not found: {exc}",
                    )
                )
            except subprocess.TimeoutExpired as exc:
                steps.append(
                    RepoVerificationStep(
                        command=cmd.raw,
                        returncode=-1,
                        status="error",
                        stdout=_safe_text(getattr(exc, "stdout", ""))[-4000:],
                        stderr=f"Timed out after {exc.timeout}s",
                    )
                )
            except Exception as exc:  # pragma: no cover - defensive
                steps.append(
                    RepoVerificationStep(
                        command=cmd.raw,
                        returncode=-1,
                        status="error",
                        stderr=str(exc),
                    )
                )
        return steps

    def _render_verification_report(
        self,
        card: RepoTaskCard,
        steps: list[RepoVerificationStep],
    ) -> str:
        lines = [
            f"# Verification Report: {card.id}",
            "",
            f"Title: {card.title}",
            "",
        ]
        if not steps:
            lines.append("No verification commands were applicable.")
            return "\n".join(lines).strip() + "\n"
        for step in steps:
            lines.extend(
                [
                    f"## {step.status.upper()} :: {step.command}",
                    "",
                    f"Return code: {step.returncode}",
                    "",
                ]
            )
            if step.stdout:
                lines.extend(["### stdout", "```text", step.stdout, "```", ""])
            if step.stderr:
                lines.extend(["### stderr", "```text", step.stderr, "```", ""])
        return "\n".join(lines).strip() + "\n"

    def _render_run_report(
        self,
        card: RepoTaskCard,
        *,
        agent_summary: str,
        verification_steps: list[RepoVerificationStep],
        verification_status: str,
    ) -> str:
        lines = [
            f"# Autopilot Run Report: {card.id}",
            "",
            f"Title: {card.title}",
            f"Source: {card.source_kind}",
            f"Source ref: {card.source_ref or '-'}",
            "",
            "## Agent Self-Reported Summary",
            "",
            agent_summary.strip() or "(empty agent summary)",
            "",
            "## Service-Level Ground Truth",
            "",
            (
                "The section above is the model's own summary. "
                "Treat it as untrusted until the service-level verification results below finish."
            ),
            "",
        ]

        if verification_status == "not_started":
            lines.extend(
                [
                    "- Verification status: not started.",
                    "- The agent run itself failed before service-level verification could begin.",
                ]
            )
        elif verification_status == "pending":
            lines.extend(
                [
                    "- Verification status: pending.",
                    "- Service-level verification has not finished yet.",
                ]
            )
        else:
            overall = "passed" if verification_status == "passed" else "failed"
            lines.append(f"- Verification status: {overall}.")
            if verification_steps:
                for step in verification_steps:
                    lines.append(
                        f"- [{step.status}] `{step.command}` (rc={step.returncode})"
                    )
            else:
                lines.append("- No verification commands were applicable.")

        return "\n".join(lines).strip() + "\n"
