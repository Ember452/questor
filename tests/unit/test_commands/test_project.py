"""Mirror test for ``commands/families/project.py`` (plan 01, R7).

Scope note: neither ``register_git_commands`` nor ``register_project_context_commands``
was named by any test before this file. This family shells out to git and deletes/creates
files under the project directory, so the interesting contracts are: **which git argv is
run, in what order** (``/commit`` staging everything with ``add -A`` is a decision, not a
detail), what a failure is reported as, and the exact shape of the issue / PR-comment
context files. The git subprocess and the two paths are faked: no repository is touched.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from questorharness.commands.families import project
from questorharness.commands.families.project import (
    _run_git_command,
    register_git_commands,
    register_project_context_commands,
)
from questorharness.commands.models import CommandContext, CommandRegistry


class _Done:
    """CompletedProcess-shaped answer for one argv."""

    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


@pytest.fixture()
def git(monkeypatch):
    """Replace the subprocess module this family uses, and script its answers."""
    calls: list[tuple[tuple[str, ...], str]] = []
    replies: dict[tuple[str, ...], object] = {}

    def _run(argv, **kwargs):
        calls.append((tuple(argv), kwargs.get("cwd")))
        answer = replies.get(tuple(argv), _Done(stdout="OK"))
        if isinstance(answer, BaseException):
            raise answer
        return answer

    monkeypatch.setattr(project, "subprocess", SimpleNamespace(run=_run))
    return SimpleNamespace(calls=calls, replies=replies)


@pytest.fixture()
def registry() -> CommandRegistry:
    return CommandRegistry()


@pytest.fixture(autouse=True)
def registered(registry, tmp_path, monkeypatch):
    """Both families, with the context files pointed at a temporary directory."""
    paths = {
        "issue": tmp_path / "context" / "ISSUE.md",
        "pr": tmp_path / "context" / "PR_COMMENTS.md",
    }
    monkeypatch.setattr(project, "get_project_issue_file", lambda _cwd: paths["issue"])
    monkeypatch.setattr(project, "get_project_pr_comments_file", lambda _cwd: paths["pr"])
    register_git_commands(registry)
    register_project_context_commands(registry)
    registry.paths = paths  # type: ignore[attr-defined]
    return registry


def context(cwd: str = "/repo") -> CommandContext:
    return CommandContext(engine=object(), cwd=cwd)  # type: ignore[arg-type]


async def handle(registry: CommandRegistry, spoken: str, cwd: str = "/repo"):
    found = registry.lookup(spoken)
    assert found is not None, f"{spoken} is not registered"
    command, args = found
    return await command.handler(args, context(cwd))


# --- the git wrapper itself -----------------------------------------------


def test_stdout_is_preferred_and_both_streams_are_stripped(git) -> None:
    git.replies[("git", "status", "--short")] = _Done(stdout="  M a.py \n", stderr="ignored", returncode=0)

    assert _run_git_command("/repo", "status", "--short") == (True, "M a.py")


def test_stderr_is_used_when_stdout_is_empty(git) -> None:
    git.replies[("git", "diff", "--stat")] = _Done(stdout="", stderr="warning: in the working copy\n", returncode=0)

    assert _run_git_command("/repo", "diff", "--stat") == (True, "warning: in the working copy")


def test_a_failing_git_with_no_output_gets_a_synthesised_message(git) -> None:
    git.replies[("git", "diff", "HEAD")] = _Done(stdout="", stderr="", returncode=128)

    ok, message = _run_git_command("/repo", "diff", "HEAD")

    assert ok is False
    assert message == "git diff HEAD failed"


def test_a_failing_git_keeps_its_own_message(git) -> None:
    git.replies[("git", "branch", "--show-current")] = _Done(stderr="not a git repository", returncode=128)

    assert _run_git_command("/repo", "branch", "--show-current") == (False, "not a git repository")


def test_a_missing_git_binary_is_named_as_such(git) -> None:
    git.replies[("git", "status", "--short")] = FileNotFoundError("git")

    assert _run_git_command("/repo", "status", "--short") == (False, "git is not installed.")


def test_the_repository_root_is_passed_as_cwd(git) -> None:
    _run_git_command(r"D:\proj", "diff", "--stat")

    assert git.calls == [(("git", "diff", "--stat"), r"D:\proj")]


# --- /diff ----------------------------------------------------------------


async def test_diff_defaults_to_a_stat_and_diff_full_to_the_whole_tree(registry, git) -> None:
    await handle(registry, "/diff")
    assert git.calls[-1][0] == ("git", "diff", "--stat")

    await handle(registry, "/diff full")
    assert git.calls[-1][0] == ("git", "diff", "HEAD")


async def test_an_empty_diff_says_so_rather_than_printing_nothing(registry, git) -> None:
    git.replies[("git", "diff", "--stat")] = _Done(stdout="")

    assert (await handle(registry, "/diff")).message == "(no diff)"


async def test_a_failed_diff_is_reported_as_its_message(registry, git) -> None:
    git.replies[("git", "diff", "--stat")] = _Done(stderr="bad revision", returncode=1)

    assert (await handle(registry, "/diff")).message == "bad revision"


# --- /branch --------------------------------------------------------------


async def test_show_names_the_branch_or_calls_it_detached(registry, git) -> None:
    assert (await handle(registry, "/branch")).message == "Current branch: OK"

    git.replies[("git", "branch", "--show-current")] = _Done(stdout="")
    assert (await handle(registry, "/branch show")).message == "Current branch: (detached HEAD)"


async def test_a_failed_show_does_not_claim_a_branch(registry, git) -> None:
    git.replies[("git", "branch", "--show-current")] = _Done(stderr="not a git repository", returncode=128)

    assert (await handle(registry, "/branch")).message == "not a git repository"


async def test_list_uses_a_format_string_and_passes_three_separate_args(registry, git) -> None:
    await handle(registry, "/branch list")

    assert git.calls[-1][0] == ("git", "branch", "--format", "%(refname:short)")


async def test_a_failed_list_is_printed_exactly_like_a_successful_one(registry, git) -> None:
    """Pinned, not blessed: ``branches if ok else branches`` is a no-op conditional.

    A failed list carries no error marker, so the caller cannot tell an empty repository
    from a broken git. Ledger #126 records it instead of dressing it up.
    """
    git.replies[("git", "branch", "--format", "%(refname:short)")] = _Done(stderr="fatal", returncode=1)

    assert (await handle(registry, "/branch list")).message == "fatal"


async def test_an_unknown_branch_action_shows_the_usage(registry, git) -> None:
    assert (await handle(registry, "/branch create feature")).message == "Usage: /branch [show|list]"


# --- /commit --------------------------------------------------------------


async def test_commit_without_a_message_is_a_status_view(registry, git) -> None:
    git.replies[("git", "status", "--short")] = _Done(stdout="M a.py\n")

    assert (await handle(registry, "/commit")).message == "M a.py"


async def test_a_clean_or_unreadable_status_both_read_as_clean(registry, git) -> None:
    """Pinned, not blessed: a *failing* ``git status`` is also reported as clean.

    ``status if ok and status else "(working tree clean)"`` cannot tell the two apart,
    so a broken repository looks empty. Asserted so the fix is deliberate.
    """
    git.replies[("git", "status", "--short")] = _Done(stdout="", returncode=0)
    assert (await handle(registry, "/commit")).message == "(working tree clean)"

    git.replies[("git", "status", "--short")] = _Done(stderr="not a git repository", returncode=128)
    assert (await handle(registry, "/commit")).message == "(working tree clean)"


async def test_commit_refuses_to_create_an_empty_commit(registry, git) -> None:
    git.replies[("git", "status", "--short")] = _Done(stdout="   \n", returncode=0)

    assert (await handle(registry, "/commit fix it")).message == "Nothing to commit."
    assert [call[0] for call in git.calls] == [("git", "status", "--short")]


async def test_commit_stages_everything_with_add_A_before_committing(registry, git) -> None:
    """Pinned: ``/commit`` runs ``add -A``, so a partly staged tree is overwritten."""
    result = await handle(registry, "/commit  fix it  ")

    assert [call[0] for call in git.calls] == [
        ("git", "status", "--short"),
        ("git", "add", "-A"),
        ("git", "commit", "-m", "fix it"),
    ]
    assert result.message == "OK"


async def test_a_failing_stage_stops_before_the_commit(registry, git) -> None:
    git.replies[("git", "add", "-A")] = _Done(stderr="permission denied", returncode=1)

    assert (await handle(registry, "/commit fix it")).message == "permission denied"
    assert ("git", "commit", "-m", "fix it") not in [call[0] for call in git.calls]


async def test_a_failing_commit_returns_gits_message(registry, git) -> None:
    git.replies[("git", "commit", "-m", "fix it")] = _Done(stderr="nothing added to commit", returncode=1)

    assert (await handle(registry, "/commit fix it")).message == "nothing added to commit"


# --- /issue ---------------------------------------------------------------


async def test_showing_a_missing_issue_context_points_at_the_file(registry, git) -> None:
    path = registry.paths["issue"]

    assert (await handle(registry, "/issue")).message == f"No issue context. File path: {path}"


async def test_showing_an_issue_returns_the_file_contents(registry, git) -> None:
    path = registry.paths["issue"]
    path.parent.mkdir(parents=True)
    path.write_text("# Body from disk\n", encoding="utf-8")

    assert (await handle(registry, "/issue show")).message == "# Body from disk\n"


@pytest.mark.parametrize("rest", ["no separator here", ":: body only", "title only ::", "   ::   "])
async def test_a_set_without_both_halves_writes_nothing(registry, git, rest: str) -> None:
    assert (await handle(registry, f"/issue set {rest}")).message == "Usage: /issue set TITLE :: BODY"
    assert not registry.paths["issue"].exists()


async def test_set_writes_the_markdown_shape_and_creates_the_directory(registry, git) -> None:
    result = await handle(registry, "/issue set My Title :: first line\nsecond line")

    assert result.message == f"Saved issue context to {registry.paths['issue']}"
    assert registry.paths["issue"].read_text(encoding="utf-8") == "# My Title\n\nfirst line\nsecond line\n"


async def test_clear_removes_the_file_once_and_then_says_there_is_nothing(registry, git) -> None:
    registry.paths["issue"].parent.mkdir(parents=True)
    registry.paths["issue"].write_text("# x\n", encoding="utf-8")

    assert (await handle(registry, "/issue clear")).message == "Cleared issue context."
    assert not registry.paths["issue"].exists()
    assert (await handle(registry, "/issue clear")).message == "No issue context to clear."


async def test_an_unrecognised_issue_action_shows_the_full_usage(registry, git) -> None:
    assert (await handle(registry, "/issue rename x")).message == (
        "Usage: /issue [show|set TITLE :: BODY|clear]"
    )


# --- /pr_comments ---------------------------------------------------------


async def test_adding_the_first_comment_creates_the_header(registry, git) -> None:
    result = await handle(registry, "/pr_comments add src/a.py:12 :: 这里少一个括号")

    assert result.message == f"Added PR comment to {registry.paths['pr']}"
    assert registry.paths["pr"].read_text(encoding="utf-8") == "# PR Comments\n- src/a.py:12: 这里少一个括号\n"


async def test_adding_appends_and_repairs_a_missing_trailing_newline(registry, git) -> None:
    path = registry.paths["pr"]
    path.parent.mkdir(parents=True)
    path.write_text("# PR Comments\n- old: kept", encoding="utf-8")

    await handle(registry, "/pr_comments add b.py :: second")

    assert path.read_text(encoding="utf-8") == "# PR Comments\n- old: kept\n- b.py: second\n"


async def test_the_location_and_comment_are_stripped_into_the_line(registry, git) -> None:
    await handle(registry, "/pr_comments add   c.py  ::   spaced   ")

    assert registry.paths["pr"].read_text(encoding="utf-8").splitlines()[-1] == "- c.py: spaced"


@pytest.mark.parametrize("rest", ["missing separator", ":: no location", "location ::"])
async def test_an_incomplete_add_writes_nothing(registry, git, rest: str) -> None:
    assert (await handle(registry, f"/pr_comments add {rest}")).message == (
        "Usage: /pr_comments add FILE[:LINE] :: COMMENT"
    )
    assert not registry.paths["pr"].exists()


async def test_showing_pr_comments_covers_both_missing_and_present(registry, git) -> None:
    assert (await handle(registry, "/pr_comments")).message == f"No PR comments context. File path: {registry.paths['pr']}"

    registry.paths["pr"].parent.mkdir(parents=True)
    registry.paths["pr"].write_text("- a\n", encoding="utf-8")
    assert (await handle(registry, "/pr_comments show")).message == "- a\n"


async def test_clearing_pr_comments_reports_both_outcomes(registry, git) -> None:
    assert (await handle(registry, "/pr_comments clear")).message == "No PR comments context to clear."

    registry.paths["pr"].parent.mkdir(parents=True)
    registry.paths["pr"].write_text("- a\n", encoding="utf-8")
    assert (await handle(registry, "/pr_comments clear")).message == "Cleared PR comments context."
    assert not registry.paths["pr"].exists()


async def test_an_unrecognised_pr_comments_action_shows_the_usage(registry, git) -> None:
    assert (await handle(registry, "/pr_comments drop")).message == (
        "Usage: /pr_comments [show|add FILE[:LINE] :: COMMENT|clear]"
    )


# --- who may trigger them remotely ---------------------------------------


def test_only_branch_is_remotely_invocable(registry, git) -> None:
    """Pinned: the commands that write files or history are terminal-only."""
    for name in ("diff", "commit", "issue", "pr_comments"):
        command, _ = registry.lookup(f"/{name}")
        assert command.remote_invocable is False
        assert command.remote_admin_opt_in is True
    assert registry.lookup("/branch")[0].remote_invocable is True
