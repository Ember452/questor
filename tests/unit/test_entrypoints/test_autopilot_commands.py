"""Mirror test for ``bootstrap/cli/autopilot_commands.py`` (plan 01, R7).

Scope note: none of the ten commands nor ``autopilot_app`` was named by any test before
this file. The commands are shells over ``RepoAutopilotStore``, but the shell owns every
user-visible decision: which statuses get printed and in what order, that the listing
shows only the first twenty cards, which short names the ``add`` source accepts, and
that an unknown target exits non-zero instead of printing a friendly nothing.
The store is replaced wholesale -- no git, no GitHub, no model run.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from questorharness.bootstrap.cli.autopilot_commands import autopilot_app

runner = CliRunner()

STATUS_ORDER = (
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
)


def card(**overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "id": "auto-1",
        "status": "queued",
        "score": 10,
        "title": "Fix the flaky test",
        "source_kind": "manual_idea",
        "source_ref": "",
        "body": "",
    }
    return SimpleNamespace(**base | overrides)  # type: ignore[arg-type]


def run(*args: str):
    return runner.invoke(autopilot_app, list(args))


def stderr_of(result) -> str:
    """Read the error stream without pinning the test to one click version."""
    try:
        return result.stderr
    except (ValueError, AttributeError):  # pragma: no cover - older click merged the streams
        return result.output


class _Coro:
    """A scripted value the CLI can hand to ``asyncio.run``.

    ``run-next`` and ``tick`` await their store, so the fake must return a fresh
    coroutine rather than the object itself.
    """

    def __init__(self, value: object) -> None:
        self.value = value

    def make(self):
        async def _run():
            return self.value

        return _run()


@pytest.fixture()
def store(monkeypatch):
    """Swap in a store that records calls and returns scripted values."""
    calls: list[tuple[str, tuple, dict]] = []
    values: dict[str, object] = {
        "stats": {"queued": 2, "running": 1},
        "pick_next_card": None,
        "list_cards": [],
        "enqueue_card": (card(), True),
        "load_active_context": "ACTIVE CONTEXT",
        "load_journal": [],
        "scan_github_issues": [1, 2, 3],
        "scan_github_prs": [1],
        "scan_claude_code_candidates": [1, 2],
        "scan_all_sources": {"issues": 1, "note": "\u4e2d\u6587"},
        "run_next": _Coro(
            SimpleNamespace(
                card_id="auto-1", status="merged", run_report_path="r.json", verification_report_path="v.json"
            )
        ),
        "tick": _Coro(None),
        "install_default_cron": ["autopilot-scan", "autopilot-tick"],
        "export_dashboard": "site/index.html",
    }

    class _FakeStore:
        registry_path = "REGISTRY.json"
        journal_path = "JOURNAL.jsonl"
        context_path = "CONTEXT.md"

        def __init__(self, cwd: str) -> None:
            calls.append(("__init__", (cwd,), {}))

        def __getattr__(self, name: str):
            def _call(*args, **kwargs):
                calls.append((name, args, kwargs))
                value = values[name]
                if isinstance(value, Exception):
                    raise value
                if isinstance(value, _Coro):
                    return value.make()
                return value

            return _call

    monkeypatch.setattr("questorharness.runtime.autopilot.RepoAutopilotStore", _FakeStore)
    return SimpleNamespace(calls=calls, values=values)


def invoked(store, name: str) -> tuple[tuple, dict]:
    """The (args, kwargs) of the last call to ``name``."""
    for called, args, kwargs in reversed(store.calls):
        if called == name:
            return args, kwargs
    raise AssertionError(f"{name} was never called: {[c[0] for c in store.calls]}")


# --- status ---------------------------------------------------------------


def test_status_prints_the_whole_vocabulary_in_order_even_when_empty(store) -> None:
    out = run("status").output.splitlines()

    assert out[0] == "Autopilot queue status:"
    assert [line.strip().split(":")[0] for line in out[1:14]] == list(STATUS_ORDER)
    assert "  queued: 2" in out
    assert "  running: 1" in out
    # a status nobody has reached is still listed, as zero
    assert "  superseded: 0" in out
    assert not [line for line in out if line.strip().startswith("next:")]


def test_status_shows_the_next_card_and_the_three_file_paths(store) -> None:
    store.values["pick_next_card"] = card(id="auto-7", title="Repair CI", score=12)

    out = run("status").output

    assert "  next: auto-7 Repair CI (score=12)" in out
    assert "  registry: REGISTRY.json" in out
    assert "  journal: JOURNAL.jsonl" in out
    assert "  context: CONTEXT.md" in out


def test_the_repository_root_is_passed_to_the_store(store) -> None:
    run("status", "--cwd", r"D:\repos\app")

    assert invoked(store, "__init__")[0] == (r"D:\repos\app",)


# --- list -----------------------------------------------------------------


def test_an_empty_queue_says_so_and_does_not_filter(store) -> None:
    assert run("list").output.strip() == "No autopilot cards."
    # pinned: without a filter the store is called with *no* keyword at all, so a
    # store that treats ``status=None`` differently would behave differently here
    assert invoked(store, "list_cards") == ((), {})


def test_a_status_filter_is_forwarded_as_a_keyword(store) -> None:
    run("list", "queued")

    assert invoked(store, "list_cards") == ((), {"status": "queued"})


def test_the_listing_is_capped_at_twenty_cards(store) -> None:
    """Pinned: cards 21..25 exist but are never shown, and nothing says "more"."""
    store.values["list_cards"] = [card(id=f"auto-{i}") for i in range(1, 26)]

    out = run("list").output

    assert out.count("auto-") == 20
    assert "auto-20" in out
    assert "auto-21" not in out


def test_a_card_is_rendered_with_status_score_source_and_reference(store) -> None:
    store.values["list_cards"] = [card(id="auto-3", status="running", score=7, title="T", source_ref="42", body="")]

    out = run("list").output.splitlines()

    assert out[0] == "auto-3 [running] score=7 T"
    assert out[1] == "  source=manual_idea ref=42"
    assert len(out) == 2, "an empty body must not print a blank detail line"


def test_the_body_is_flattened_and_capped(store) -> None:
    store.values["list_cards"] = [card(body="first\nsecond   line"), card(id="auto-9", body="q" * 200)]

    lines = run("list").output.splitlines()

    assert lines[2] == "  first second line"
    assert lines[5] == "  " + "q" * 137 + "..."


# --- add ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spoken", "stored"),
    [
        ("idea", "manual_idea"),
        ("manual", "manual_idea"),
        ("MANUAL", "manual_idea"),
        ("questor", "questor_request"),
        ("issue", "github_issue"),
        ("pr", "github_pr"),
        ("claude", "claude_code_candidate"),
        ("github_pr", "github_pr"),
    ],
)
def test_source_shorthands_become_the_canonical_kind(store, spoken, stored) -> None:
    run("add", spoken, "Ship it", "--body", "details")

    assert invoked(store, "enqueue_card")[1] == {"source_kind": stored, "title": "Ship it", "body": "details"}


def test_a_new_card_is_queued_and_a_repeat_is_refreshed(store) -> None:
    out = run("add", "idea", "T").output.strip()
    assert out == "Queued auto-1 (score=10): Fix the flaky test"

    store.values["enqueue_card"] = (card(id="auto-2", title="T"), False)
    assert run("add", "idea", "T").output.startswith("Refreshed auto-2")


def test_an_unknown_source_exits_non_zero_without_touching_the_store(store) -> None:
    result = run("add", "jira", "T")

    assert result.exit_code == 1
    assert "Unknown source kind: jira" in stderr_of(result)
    assert not [name for name, _, _ in store.calls if name == "enqueue_card"]


def test_the_source_is_the_first_positional_and_the_title_is_required(store) -> None:
    """Pinned, not blessed: ``add TITLE`` does not add a card.

    ``source`` carries a default while ``title`` does not, so a single argument lands on
    the source and the command fails. Users will hit this; changing the order later is a
    breaking CLI change, which is exactly why it is written down here.
    """
    result = run("add", "just-a-title")

    assert result.exit_code != 0
    assert not [name for name, _, _ in store.calls if name == "enqueue_card"]


# --- context / journal ----------------------------------------------------


def test_context_prints_the_synthesized_text_verbatim(store) -> None:
    assert run("context").output.strip() == "ACTIVE CONTEXT"


def test_an_empty_journal_is_called_out(store) -> None:
    assert run("journal").output.strip() == "Repo journal is empty."


def test_journal_lines_default_to_twelve_entries_and_use_a_dash_for_a_missing_id(store) -> None:
    store.values["load_journal"] = [
        SimpleNamespace(kind="scan", task_id="auto-1", summary="found 3"),
        SimpleNamespace(kind="run", task_id=None, summary="merged"),
    ]

    out = run("journal").output

    assert invoked(store, "load_journal")[1] == {"limit": 12}
    assert "scan auto-1 found 3" in out
    assert "run - merged" in out

    run("journal", "-n", "3")
    assert invoked(store, "load_journal")[1] == {"limit": 3}


# --- scan -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("target", "method", "count", "noun"),
    [
        ("issues", "scan_github_issues", 3, "GitHub issues"),
        ("prs", "scan_github_prs", 1, "GitHub PRs"),
        ("claude-code", "scan_claude_code_candidates", 2, "claude-code candidates"),
    ],
)
def test_each_scan_target_reports_its_own_count(store, target, method, count, noun) -> None:
    assert run("scan", target).output.strip() == f"Scanned {count} {noun}."
    assert invoked(store, method)[1] == {"limit": 10}


def test_scanning_all_prints_one_json_document_with_readable_text(store) -> None:
    out = run("scan", "all", "--limit", "4").output.strip()

    assert json.loads(out) == {"issues": 1, "note": "\u4e2d\u6587"}
    # ensure_ascii=False: the raw text is on the wire, not \\uXXXX escapes
    assert "\u4e2d\u6587" in out
    assert invoked(store, "scan_all_sources")[1] == {"issue_limit": 4, "pr_limit": 4}


def test_an_unknown_scan_target_exits_non_zero(store) -> None:
    result = run("scan", "tickets")

    assert result.exit_code == 1
    assert "Unknown scan target: tickets" in stderr_of(result)


# --- run-next / tick ------------------------------------------------------


def test_running_the_next_card_reports_the_card_and_both_report_paths(store) -> None:
    out = run("run-next").output.splitlines()

    assert out == ["auto-1 -> merged", "run report: r.json", "verification report: v.json"]
    assert invoked(store, "run_next")[1] == {"model": None, "max_turns": None, "permission_mode": None}


def test_the_execution_overrides_are_forwarded(store) -> None:
    run("run-next", "--model", "opus", "--max-turns", "5", "--permission-mode", "plan")

    assert invoked(store, "run_next")[1] == {"model": "opus", "max_turns": 5, "permission_mode": "plan"}


def test_an_empty_queue_is_reported_as_an_error_not_a_success(store) -> None:
    store.values["run_next"] = ValueError("no queued cards")

    result = run("run-next")

    assert result.exit_code == 1
    assert "no queued cards" in stderr_of(result)
    assert "->" not in result.output, "a failed run must not look like a completed one"


def test_a_tick_that_does_not_run_says_so(store) -> None:
    out = run("tick").output.strip()

    assert out == "Autopilot tick completed with no execution."
    assert invoked(store, "tick")[1] == {
        "model": None,
        "max_turns": None,
        "permission_mode": None,
        "issue_limit": 10,
        "pr_limit": 10,
    }


def test_a_tick_that_runs_shares_the_run_next_output(store) -> None:
    store.values["tick"] = store.values["run_next"]

    out = run("tick", "-n", "7", "--model", "haiku").output.splitlines()

    assert out[0] == "auto-1 -> merged"
    assert invoked(store, "tick")[1]["issue_limit"] == 7
    assert invoked(store, "tick")[1]["pr_limit"] == 7
    assert invoked(store, "tick")[1]["model"] == "haiku"


def test_only_a_value_error_becomes_a_clean_exit(store) -> None:
    """Pinned, not blessed: the shell converts ``ValueError`` and nothing else.

    A store that raises any other error lets it escape as a traceback instead of a
    one-line failure, so a half-finished scan is not turned into a tidy exit message.
    """
    store.values["tick"] = RuntimeError("scan blew up")

    result = run("tick")

    assert isinstance(result.exception, RuntimeError)


# --- install-cron / export-dashboard --------------------------------------


def test_installed_cron_jobs_are_listed(store) -> None:
    assert run("install-cron").output.strip() == "Installed cron jobs: autopilot-scan, autopilot-tick"


def test_the_dashboard_output_directory_is_passed_positionally(store) -> None:
    out = run("export-dashboard", "--output", "site").output.strip()

    assert out == "Exported autopilot dashboard: site/index.html"
    assert invoked(store, "export_dashboard")[0] == ("site",)


def test_the_command_group_is_registered_under_the_app(store) -> None:
    assert autopilot_app.info.name == "autopilot"
    assert autopilot_app.info.help == "Manage repo autopilot"
    assert {command.name for command in autopilot_app.registered_commands} == {
        "status",
        "list",
        "add",
        "context",
        "journal",
        "scan",
        "run-next",
        "tick",
        "install-cron",
        "export-dashboard",
    }
