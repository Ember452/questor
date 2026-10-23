"""Register background-task, autopilot and ship commands."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from questorharness.runtime.autopilot import RepoAutopilotStore
from questorharness.runtime.tasks import get_task_manager

from questorharness.commands.types import (
    CommandContext,
    CommandRegistry,
    CommandResult,
    SlashCommand,
)


def _shorten_text(text: str, *, limit: int = 160) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def register_agents_commands(registry: CommandRegistry) -> None:
    """Register background-task, autopilot and ship commands."""

    async def _agents_handler(args: str, context: CommandContext) -> CommandResult:
        tokens = args.split(maxsplit=1)
        guide = (
            "Subagent guide:\n"
            "- Ask the model to delegate with the `agent` tool when the task needs background work or parallel investigation.\n"
            '- The usual worker shape is subagent_type="worker".\n'
            "- /agents lists known worker tasks.\n"
            "- /agents show TASK_ID shows one worker's output and metadata.\n"
            "- send_message(task_id=..., message=...) can continue a spawned worker.\n"
            "- task_output(task_id=...) reads the worker's latest output."
        )
        if tokens and tokens[0] in {"help", "usage"}:
            return CommandResult(
                message=guide
            )
        if tokens and tokens[0] == "show" and len(tokens) == 2:
            task = get_task_manager().get_task(tokens[1])
            if task is None or task.type not in {"local_agent", "remote_agent", "in_process_teammate"}:
                return CommandResult(message=f"No agent found with ID: {tokens[1]}")
            output = get_task_manager().read_task_output(task.id)
            return CommandResult(
                message=(
                    f"{task.id} {task.type} {task.status} {task.description}\n"
                    f"metadata={task.metadata}\n"
                    f"output:\n{output or '(no output)'}"
                )
            )
        tasks = [
            task
            for task in get_task_manager().list_tasks()
            if task.type in {"local_agent", "remote_agent", "in_process_teammate"}
        ]
        if not tasks:
            return CommandResult(
                message=f"No active or recorded agents. Run /agents help for usage.\n\n{guide}"
            )
        lines = [
            f"{task.id} {task.type} {task.status} {task.description}"
            for task in tasks
        ]
        return CommandResult(message="\n".join(lines))

    async def _tasks_handler(args: str, context: CommandContext) -> CommandResult:
        manager = get_task_manager()
        tokens = args.split(maxsplit=2)
        if not tokens or tokens[0] == "list":
            tasks = manager.list_tasks()
            if not tasks:
                return CommandResult(message="No background tasks.")
            return CommandResult(
                message="\n".join(f"{task.id} {task.type} {task.status} {task.description}" for task in tasks)
            )
        if tokens[0] == "run" and len(tokens) >= 2:
            command = args[len("run ") :]
            task = await manager.create_shell_task(
                command=command,
                description=command[:80],
                cwd=context.cwd,
            )
            return CommandResult(message=f"Started task {task.id}")
        if tokens[0] == "stop" and len(tokens) == 2:
            task = await manager.stop_task(tokens[1])
            return CommandResult(message=f"Stopped task {task.id}")
        if tokens[0] == "show" and len(tokens) == 2:
            task = manager.get_task(tokens[1])
            if task is None:
                return CommandResult(message=f"No task found with ID: {tokens[1]}")
            return CommandResult(message=str(task))
        if tokens[0] == "update" and len(tokens) == 3:
            task_id = tokens[1]
            rest = tokens[2]
            field, _, value = rest.partition(" ")
            if not value.strip():
                return CommandResult(
                    message="Usage: /tasks update ID [description TEXT|progress NUMBER|note TEXT]"
                )
            try:
                if field == "description":
                    task = manager.update_task(task_id, description=value)
                    return CommandResult(message=f"Updated task {task.id} description")
                if field == "progress":
                    try:
                        progress = int(value)
                    except ValueError:
                        return CommandResult(message="Progress must be an integer between 0 and 100.")
                    task = manager.update_task(task_id, progress=progress)
                    return CommandResult(message=f"Updated task {task.id} progress to {progress}%")
                if field == "note":
                    task = manager.update_task(task_id, status_note=value)
                    return CommandResult(message=f"Updated task {task.id} note")
            except ValueError as exc:
                return CommandResult(message=str(exc))
            return CommandResult(
                message="Usage: /tasks update ID [description TEXT|progress NUMBER|note TEXT]"
            )
        if tokens[0] == "output" and len(tokens) == 2:
            return CommandResult(message=manager.read_task_output(tokens[1]) or "(no output)")
        return CommandResult(
            message=(
                "Usage: /tasks "
                "[list|run CMD|stop ID|show ID|update ID description TEXT|update ID progress NUMBER|update ID note TEXT|output ID]"
            )
        )

    async def _autopilot_handler(args: str, context: CommandContext) -> CommandResult:
        store = RepoAutopilotStore(context.cwd)
        tokens = args.split()
        action = tokens[0].lower() if tokens else "status"

        def _render_card(card) -> str:
            lines = [
                f"{card.id} [{card.status}] score={card.score} {card.title}",
                f"source={card.source_kind} ref={card.source_ref or '-'}",
            ]
            if card.labels:
                lines.append(f"labels={', '.join(card.labels)}")
            if card.score_reasons:
                lines.append(f"reasons={', '.join(card.score_reasons[:4])}")
            if card.body:
                lines.append(_shorten_text(card.body, limit=220))
            return "\n".join(lines)

        if action == "status":
            counts = store.stats()
            active = store.pick_next_card()
            lines = ["Autopilot queue status:"]
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
                lines.append(f"- {status_name}: {counts.get(status_name, 0)}")
            lines.append(f"- registry: {store.registry_path}")
            lines.append(f"- journal: {store.journal_path}")
            lines.append(f"- context: {store.context_path}")
            if active is not None:
                lines.append(f"- next: {active.id} {active.title} (score={active.score})")
            return CommandResult(message="\n".join(lines))

        if action == "list":
            status = tokens[1].lower() if len(tokens) >= 2 else None
            if status is not None and status not in {
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
            }:
                return CommandResult(message=f"Unknown autopilot status: {status}")
            cards = store.list_cards(status=status)
            if not cards:
                return CommandResult(message="No autopilot cards.")
            return CommandResult(message="\n\n".join(_render_card(card) for card in cards[:12]))

        if action == "show" and len(tokens) >= 2:
            card = store.get_card(tokens[1])
            if card is None:
                return CommandResult(message=f"No autopilot card found with ID: {tokens[1]}")
            return CommandResult(message=_render_card(card))

        if action == "next":
            card = store.pick_next_card()
            if card is None:
                return CommandResult(message="No queued autopilot cards.")
            return CommandResult(message=_render_card(card))

        if action == "context":
            content = store.load_active_context()
            return CommandResult(message=content or "Active repo context is empty.")

        if action == "journal":
            limit = 8
            if len(tokens) >= 2:
                try:
                    limit = max(1, min(30, int(tokens[1])))
                except ValueError:
                    return CommandResult(message="Usage: /autopilot journal [LIMIT]")
            entries = store.load_journal(limit=limit)
            if not entries:
                return CommandResult(message="Repo journal is empty.")
            lines = []
            for entry in entries:
                timestamp = datetime.fromtimestamp(entry.timestamp, tz=timezone.utc).strftime(
                    "%Y-%m-%d %H:%M UTC"
                )
                task_suffix = f" [{entry.task_id}]" if entry.task_id else ""
                lines.append(f"{timestamp} {entry.kind}{task_suffix}: {entry.summary}")
            return CommandResult(message="\n".join(lines))

        if action == "add":
            raw = args[len("add") :].strip()
            if not raw:
                return CommandResult(
                    message=(
                        "Usage: /autopilot add "
                        "[idea|questor|issue|pr|claude] TITLE :: DETAILS"
                    )
                )
            source_kind = "manual_idea"
            source_map = {
                "idea": "manual_idea",
                "manual": "manual_idea",
                "questor": "questor_request",
                "issue": "github_issue",
                "pr": "github_pr",
                "claude": "claude_code_candidate",
            }
            if " " in raw:
                first, remainder = raw.split(" ", 1)
                mapped = source_map.get(first.lower())
                if mapped is not None:
                    source_kind = mapped
                    raw = remainder.strip()
            title, _, body = raw.partition("::")
            if not title.strip():
                return CommandResult(
                    message=(
                        "Usage: /autopilot add "
                        "[idea|questor|issue|pr|claude] TITLE :: DETAILS"
                    )
                )
            card, created = store.enqueue_card(
                source_kind=source_kind,
                title=title.strip(),
                body=body.strip(),
            )
            status_word = "Queued" if created else "Refreshed"
            return CommandResult(
                message=f"{status_word} autopilot card {card.id} (score={card.score}): {card.title}"
            )

        if action in {"accept", "start", "complete", "reject", "fail"} and len(tokens) >= 2:
            status_map = {
                "accept": "accepted",
                "start": "running",
                "complete": "completed",
                "fail": "failed",
                "reject": "rejected",
            }
            note = ""
            if len(tokens) >= 3:
                note = args.split(maxsplit=2)[2]
            try:
                card = store.update_status(tokens[1], status=status_map[action], note=note or None)
            except ValueError as exc:
                return CommandResult(message=str(exc))
            return CommandResult(message=f"{card.id} -> {card.status}: {card.title}")

        if action == "run-next":
            try:
                result = await store.run_next()
            except ValueError as exc:
                return CommandResult(message=str(exc))
            return CommandResult(
                message=(
                    f"{result.card_id} -> {result.status}\n"
                    f"run report: {result.run_report_path}\n"
                    f"verification report: {result.verification_report_path}"
                )
            )

        if action == "tick":
            try:
                result = await store.tick()
            except ValueError as exc:
                return CommandResult(message=str(exc))
            if result is None:
                return CommandResult(message="Autopilot tick completed with no execution.")
            return CommandResult(
                message=(
                    f"Autopilot tick executed {result.card_id} -> {result.status}\n"
                    f"run report: {result.run_report_path}\n"
                    f"verification report: {result.verification_report_path}"
                )
            )

        if action == "install-cron":
            names = store.install_default_cron()
            return CommandResult(message="Installed autopilot cron jobs: " + ", ".join(names))

        if action == "export-dashboard":
            output = tokens[1] if len(tokens) >= 2 else None
            path = store.export_dashboard(output)
            return CommandResult(message=f"Exported autopilot dashboard: {path}")

        if action == "scan":
            if len(tokens) < 2:
                return CommandResult(
                    message="Usage: /autopilot scan [issues|prs|claude-code|all] [LIMIT]"
                )
            target = tokens[1].lower()
            limit = 10
            if len(tokens) >= 3:
                try:
                    limit = max(1, min(50, int(tokens[2])))
                except ValueError:
                    return CommandResult(
                        message="Usage: /autopilot scan [issues|prs|claude-code|all] [LIMIT]"
                    )
            try:
                if target == "issues":
                    cards = store.scan_github_issues(limit=limit)
                    return CommandResult(message=f"Scanned {len(cards)} GitHub issues into autopilot.")
                if target == "prs":
                    cards = store.scan_github_prs(limit=limit)
                    return CommandResult(message=f"Scanned {len(cards)} GitHub PRs into autopilot.")
                if target == "claude-code":
                    cards = store.scan_claude_code_candidates(limit=limit)
                    return CommandResult(
                        message=f"Scanned {len(cards)} claude-code candidates into autopilot."
                    )
                if target == "all":
                    counts = store.scan_all_sources(issue_limit=limit, pr_limit=limit)
                    return CommandResult(message=f"Scanned all sources: {json.dumps(counts)}")
            except ValueError as exc:
                return CommandResult(message=str(exc))
            return CommandResult(
                message="Usage: /autopilot scan [issues|prs|claude-code|all] [LIMIT]"
            )

        return CommandResult(
            message=(
                "Usage: /autopilot "
                "[status|list [STATUS]|show ID|next|context|journal [LIMIT]|"
                "add [idea|questor|issue|pr|claude] TITLE :: DETAILS|"
                "accept ID|start ID|complete ID [NOTE]|fail ID [NOTE]|reject ID [NOTE]|"
                "run-next|tick|install-cron|export-dashboard [OUTPUT]|"
                "scan [issues|prs|claude-code|all] [LIMIT]]"
            )
        )

    async def _ship_handler(args: str, context: CommandContext) -> CommandResult:
        raw = args.strip()
        if not raw:
            return CommandResult(message="Usage: /ship TITLE :: DETAILS")
        title, _, body = raw.partition("::")
        if not title.strip():
            return CommandResult(message="Usage: /ship TITLE :: DETAILS")
        store = RepoAutopilotStore(context.cwd)
        card, _ = store.enqueue_card(
            source_kind="questor_request",
            title=title.strip(),
            body=body.strip(),
        )
        try:
            result = await store.run_card(card.id)
        except ValueError as exc:
            return CommandResult(message=str(exc))
        return CommandResult(
            message=(
                f"{result.card_id} -> {result.status}\n"
                f"run report: {result.run_report_path}\n"
                f"verification report: {result.verification_report_path}"
            )
        )

    registry.register(SlashCommand("agents", "List or inspect agent and teammate tasks", _agents_handler))

    registry.register(SlashCommand("subagents", "Show subagent usage and inspect worker tasks", _agents_handler))

    registry.register(
        SlashCommand(
            "tasks",
            "Manage background tasks",
            _tasks_handler,
            remote_invocable=False,
            remote_admin_opt_in=True,
        )
    )

    registry.register(
        SlashCommand(
            "autopilot",
            "Manage repo autopilot intake and context",
            _autopilot_handler,
            remote_invocable=False,
            remote_admin_opt_in=True,
        )
    )

    registry.register(
        SlashCommand(
            "ship",
            "Queue and execute an questor-driven repo task",
            _ship_handler,
            remote_invocable=False,
            remote_admin_opt_in=True,
        )
    )

# questor: allow R7 -- until W8 adds the mirror test
# questor: allow R8 -- refactor the offenders in W8
