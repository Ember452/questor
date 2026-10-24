"""Register git helper commands. Register project issue and PR context commands."""

from __future__ import annotations

import subprocess
from questorharness.platform.paths import get_project_issue_file, get_project_pr_comments_file

from questorharness.commands.models import (
    CommandContext,
    CommandRegistry,
    CommandResult,
    SlashCommand,
)


def _run_git_command(cwd: str, *args: str) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False, "git is not installed."
    output = (completed.stdout or completed.stderr).strip()
    if completed.returncode != 0:
        return False, output or f"git {' '.join(args)} failed"
    return True, output


def register_git_commands(registry: CommandRegistry) -> None:
    """Register git helper commands."""

    async def _diff_handler(args: str, context: CommandContext) -> CommandResult:
        if args.strip() == "full":
            ok, output = _run_git_command(context.cwd, "diff", "HEAD")
            return CommandResult(message=output or "(no diff)")
        ok, output = _run_git_command(context.cwd, "diff", "--stat")
        if not ok:
            return CommandResult(message=output)
        return CommandResult(message=output or "(no diff)")

    async def _branch_handler(args: str, context: CommandContext) -> CommandResult:
        action = args.strip() or "show"
        if action == "show":
            ok, current = _run_git_command(context.cwd, "branch", "--show-current")
            if not ok:
                return CommandResult(message=current)
            return CommandResult(message=f"Current branch: {current or '(detached HEAD)'}")
        if action == "list":
            ok, branches = _run_git_command(context.cwd, "branch", "--format", "%(refname:short)")
            return CommandResult(message=branches if ok else branches)
        return CommandResult(message="Usage: /branch [show|list]")

    async def _commit_handler(args: str, context: CommandContext) -> CommandResult:
        message = args.strip()
        if not message:
            ok, status = _run_git_command(context.cwd, "status", "--short")
            return CommandResult(message=status if ok and status else "(working tree clean)")
        ok, status = _run_git_command(context.cwd, "status", "--short")
        if not ok:
            return CommandResult(message=status)
        if not status.strip():
            return CommandResult(message="Nothing to commit.")
        ok, output = _run_git_command(context.cwd, "add", "-A")
        if not ok:
            return CommandResult(message=output)
        ok, output = _run_git_command(context.cwd, "commit", "-m", message)
        return CommandResult(message=output if ok else output)

    registry.register(
        SlashCommand(
            "diff",
            "Show git diff output",
            _diff_handler,
            remote_invocable=False,
            remote_admin_opt_in=True,
        )
    )

    registry.register(SlashCommand("branch", "Show git branch information", _branch_handler))

    registry.register(
        SlashCommand(
            "commit",
            "Show status or create a git commit",
            _commit_handler,
            remote_invocable=False,
            remote_admin_opt_in=True,
        )
    )



def register_project_context_commands(registry: CommandRegistry) -> None:
    """Register project issue and PR context commands."""

    async def _issue_handler(args: str, context: CommandContext) -> CommandResult:
        path = get_project_issue_file(context.cwd)
        tokens = args.split(maxsplit=1)
        action = tokens[0] if tokens else "show"
        rest = tokens[1] if len(tokens) == 2 else ""
        if action == "show":
            if not path.exists():
                return CommandResult(message=f"No issue context. File path: {path}")
            return CommandResult(message=path.read_text(encoding="utf-8"))
        if action == "set" and rest:
            title, separator, body = rest.partition("::")
            if not separator or not title.strip() or not body.strip():
                return CommandResult(message="Usage: /issue set TITLE :: BODY")
            content = f"# {title.strip()}\n\n{body.strip()}\n"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return CommandResult(message=f"Saved issue context to {path}")
        if action == "clear":
            if path.exists():
                path.unlink()
                return CommandResult(message="Cleared issue context.")
            return CommandResult(message="No issue context to clear.")
        return CommandResult(message="Usage: /issue [show|set TITLE :: BODY|clear]")

    async def _pr_comments_handler(args: str, context: CommandContext) -> CommandResult:
        path = get_project_pr_comments_file(context.cwd)
        tokens = args.split(maxsplit=1)
        action = tokens[0] if tokens else "show"
        rest = tokens[1] if len(tokens) == 2 else ""
        if action == "show":
            if not path.exists():
                return CommandResult(message=f"No PR comments context. File path: {path}")
            return CommandResult(message=path.read_text(encoding="utf-8"))
        if action == "add" and rest:
            location, separator, comment = rest.partition("::")
            if not separator or not location.strip() or not comment.strip():
                return CommandResult(message="Usage: /pr_comments add FILE[:LINE] :: COMMENT")
            existing = path.read_text(encoding="utf-8") if path.exists() else "# PR Comments\n"
            if not existing.endswith("\n"):
                existing += "\n"
            existing += f"- {location.strip()}: {comment.strip()}\n"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(existing, encoding="utf-8")
            return CommandResult(message=f"Added PR comment to {path}")
        if action == "clear":
            if path.exists():
                path.unlink()
                return CommandResult(message="Cleared PR comments context.")
            return CommandResult(message="No PR comments context to clear.")
        return CommandResult(message="Usage: /pr_comments [show|add FILE[:LINE] :: COMMENT|clear]")

    registry.register(
        SlashCommand(
            "issue",
            "Show or update project issue context",
            _issue_handler,
            remote_invocable=False,
            remote_admin_opt_in=True,
        )
    )

    registry.register(
        SlashCommand(
            "pr_comments",
            "Show or update project PR comments context",
            _pr_comments_handler,
            remote_invocable=False,
            remote_admin_opt_in=True,
        )
    )
