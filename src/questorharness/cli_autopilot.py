"""``questorharness autopilot`` command group."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from questorharness.cli_preview import (
    _safe_short,
)

autopilot_app = typer.Typer(name="autopilot", help="Manage repo autopilot")


@autopilot_app.command("status")
def autopilot_status_cmd(
    cwd: str = typer.Option(str(Path.cwd()), "--cwd", help="Repository root"),
) -> None:
    """Show repo autopilot queue status."""
    from questorharness.runtime.autopilot import RepoAutopilotStore

    store = RepoAutopilotStore(cwd)
    counts = store.stats()
    print("Autopilot queue status:")
    for status_name in (
        "queued",
        "accepted",
        "preparing",
        "running",
        "verifying",
        "pr_open",
        "waiting_ci",
        "repairing",
        "completed",
        "merged",
        "failed",
        "rejected",
        "superseded",
    ):
        print(f"  {status_name}: {counts.get(status_name, 0)}")
    next_card = store.pick_next_card()
    if next_card is not None:
        print(f"  next: {next_card.id} {next_card.title} (score={next_card.score})")
    print(f"  registry: {store.registry_path}")
    print(f"  journal: {store.journal_path}")
    print(f"  context: {store.context_path}")


@autopilot_app.command("list")
def autopilot_list_cmd(
    status: str | None = typer.Argument(None, help="Optional status filter"),
    cwd: str = typer.Option(str(Path.cwd()), "--cwd", help="Repository root"),
) -> None:
    """List repo autopilot cards."""
    from questorharness.runtime.autopilot import RepoAutopilotStore

    store = RepoAutopilotStore(cwd)
    cards = store.list_cards(status=status) if status else store.list_cards()
    if not cards:
        print("No autopilot cards.")
        return
    for card in cards[:20]:
        print(f"{card.id} [{card.status}] score={card.score} {card.title}")
        print(f"  source={card.source_kind} ref={card.source_ref or '-'}")
        if card.body:
            print(f"  {_safe_short(card.body)}")


@autopilot_app.command("add")
def autopilot_add_cmd(
    source: str = typer.Argument("manual_idea", help="Source kind: idea, questor, issue, pr, claude"),
    title: str = typer.Argument(..., help="Task title"),
    body: str = typer.Option("", "--body", help="Task body/details"),
    cwd: str = typer.Option(str(Path.cwd()), "--cwd", help="Repository root"),
) -> None:
    """Add one repo autopilot card."""
    from questorharness.runtime.autopilot import RepoAutopilotStore

    source_map = {
        "idea": "manual_idea",
        "manual": "manual_idea",
        "manual_idea": "manual_idea",
        "questor": "questor_request",
        "questor_request": "questor_request",
        "issue": "github_issue",
        "github_issue": "github_issue",
        "pr": "github_pr",
        "github_pr": "github_pr",
        "claude": "claude_code_candidate",
        "claude_code_candidate": "claude_code_candidate",
    }
    source_kind = source_map.get(source.lower())
    if source_kind is None:
        print(f"Unknown source kind: {source}", file=sys.stderr)
        raise typer.Exit(1)
    store = RepoAutopilotStore(cwd)
    card, created = store.enqueue_card(source_kind=source_kind, title=title, body=body)
    state = "Queued" if created else "Refreshed"
    print(f"{state} {card.id} (score={card.score}): {card.title}")


@autopilot_app.command("context")
def autopilot_context_cmd(
    cwd: str = typer.Option(str(Path.cwd()), "--cwd", help="Repository root"),
) -> None:
    """Print the synthesized active repo context."""
    from questorharness.runtime.autopilot import RepoAutopilotStore

    store = RepoAutopilotStore(cwd)
    print(store.load_active_context())


@autopilot_app.command("journal")
def autopilot_journal_cmd(
    limit: int = typer.Option(12, "--limit", "-n", help="Number of entries"),
    cwd: str = typer.Option(str(Path.cwd()), "--cwd", help="Repository root"),
) -> None:
    """Print the recent repo autopilot journal."""
    from questorharness.runtime.autopilot import RepoAutopilotStore

    store = RepoAutopilotStore(cwd)
    entries = store.load_journal(limit=limit)
    if not entries:
        print("Repo journal is empty.")
        return
    for entry in entries:
        print(f"{entry.kind} {entry.task_id or '-'} {entry.summary}")


@autopilot_app.command("scan")
def autopilot_scan_cmd(
    target: str = typer.Argument(..., help="issues, prs, claude-code, or all"),
    limit: int = typer.Option(10, "--limit", "-n", help="Number of items"),
    cwd: str = typer.Option(str(Path.cwd()), "--cwd", help="Repository root"),
) -> None:
    """Scan one or more autopilot intake sources."""
    from questorharness.runtime.autopilot import RepoAutopilotStore

    store = RepoAutopilotStore(cwd)
    if target == "issues":
        print(f"Scanned {len(store.scan_github_issues(limit=limit))} GitHub issues.")
        return
    if target == "prs":
        print(f"Scanned {len(store.scan_github_prs(limit=limit))} GitHub PRs.")
        return
    if target == "claude-code":
        print(f"Scanned {len(store.scan_claude_code_candidates(limit=limit))} claude-code candidates.")
        return
    if target == "all":
        print(json.dumps(store.scan_all_sources(issue_limit=limit, pr_limit=limit), ensure_ascii=False))
        return
    print(f"Unknown scan target: {target}", file=sys.stderr)
    raise typer.Exit(1)


@autopilot_app.command("run-next")
def autopilot_run_next_cmd(
    cwd: str = typer.Option(str(Path.cwd()), "--cwd", help="Repository root"),
    model: str | None = typer.Option(None, "--model", help="Override execution model"),
    max_turns: int | None = typer.Option(None, "--max-turns", help="Override execution max turns"),
    permission_mode: str | None = typer.Option(None, "--permission-mode", help="Override execution permission mode"),
) -> None:
    """Run the highest-priority queued autopilot card end-to-end."""
    import asyncio

    from questorharness.runtime.autopilot import RepoAutopilotStore

    try:
        result = asyncio.run(
            RepoAutopilotStore(cwd).run_next(
                model=model,
                max_turns=max_turns,
                permission_mode=permission_mode,
            )
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise typer.Exit(1)
    print(f"{result.card_id} -> {result.status}")
    print(f"run report: {result.run_report_path}")
    print(f"verification report: {result.verification_report_path}")


@autopilot_app.command("tick")
def autopilot_tick_cmd(
    cwd: str = typer.Option(str(Path.cwd()), "--cwd", help="Repository root"),
    model: str | None = typer.Option(None, "--model", help="Override execution model"),
    max_turns: int | None = typer.Option(None, "--max-turns", help="Override execution max turns"),
    permission_mode: str | None = typer.Option(None, "--permission-mode", help="Override execution permission mode"),
    limit: int = typer.Option(10, "--limit", "-n", help="Scan limit for issues/PRs"),
) -> None:
    """Scan sources and, if idle, run the next queued autopilot task."""
    import asyncio

    from questorharness.runtime.autopilot import RepoAutopilotStore

    try:
        result = asyncio.run(
            RepoAutopilotStore(cwd).tick(
                model=model,
                max_turns=max_turns,
                permission_mode=permission_mode,
                issue_limit=limit,
                pr_limit=limit,
            )
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise typer.Exit(1)
    if result is None:
        print("Autopilot tick completed with no execution.")
        return
    print(f"{result.card_id} -> {result.status}")
    print(f"run report: {result.run_report_path}")
    print(f"verification report: {result.verification_report_path}")


@autopilot_app.command("install-cron")
def autopilot_install_cron_cmd(
    cwd: str = typer.Option(str(Path.cwd()), "--cwd", help="Repository root"),
) -> None:
    """Install default cron jobs for repo autopilot scan/tick."""
    from questorharness.runtime.autopilot import RepoAutopilotStore

    names = RepoAutopilotStore(cwd).install_default_cron()
    print("Installed cron jobs: " + ", ".join(names))


@autopilot_app.command("export-dashboard")
def autopilot_export_dashboard_cmd(
    cwd: str = typer.Option(str(Path.cwd()), "--cwd", help="Repository root"),
    output: str | None = typer.Option(None, "--output", help="Dashboard output directory"),
) -> None:
    """Export a static autopilot kanban site for GitHub Pages."""
    from questorharness.runtime.autopilot import RepoAutopilotStore

    path = RepoAutopilotStore(cwd).export_dashboard(output)
    print(f"Exported autopilot dashboard: {path}")
