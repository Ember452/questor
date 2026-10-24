"""Mirror test for ``bootstrap/cli/cron_commands.py`` (plan 01, R7).

Scope note: none of the seven commands was named by any test before this file. Each one
is a thin shell over the scheduler, but the shell is where the user-facing contract
lives: what "already running" prints, that a missing job exits non-zero, that stderr from
a *successful* run stays hidden, and how many history lines are shown. Those are the
things a refactor of the scheduler can change without any test noticing.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from questorharness.bootstrap.cli import cron_commands
from questorharness.bootstrap.cli.cron_commands import cron_app

SCHED = "questorharness.capabilities.schedule.cron_scheduler"
CRON = "questorharness.capabilities.schedule.cron"

runner = CliRunner()


@pytest.fixture()
def scheduler(monkeypatch):
    """Replace the scheduler surface; every command imports it inside its body."""
    state: dict[str, object] = {
        "running": False,
        "start_pid": 4242,
        "stopped": True,
        "status": {"running": True, "pid": 99, "enabled_jobs": 2, "total_jobs": 5, "log_file": "/tmp/cron.log"},
        "jobs": [],
        "history": [],
        "history_calls": [],
        "set_enabled_result": True,
    }

    def fake_load_history(**kwargs):
        state["history_calls"].append(kwargs)
        return state["history"]

    monkeypatch.setattr(f"{SCHED}.is_scheduler_running", lambda: state["running"], raising=False)
    monkeypatch.setattr(f"{SCHED}.start_daemon", lambda: state["start_pid"], raising=False)
    monkeypatch.setattr(f"{SCHED}.stop_scheduler", lambda: state["stopped"], raising=False)
    monkeypatch.setattr(f"{SCHED}.scheduler_status", lambda: state["status"], raising=False)
    monkeypatch.setattr(f"{SCHED}.load_history", fake_load_history, raising=False)
    monkeypatch.setattr(f"{CRON}.load_cron_jobs", lambda: state["jobs"], raising=False)
    monkeypatch.setattr(f"{CRON}.set_job_enabled", lambda name, enabled: state["set_enabled_result"], raising=False)
    return state


def run(*args: str):
    return runner.invoke(cron_app, list(args))


# --- start / stop ---------------------------------------------------------


def test_starting_an_already_running_scheduler_does_not_start_a_second_one(scheduler, monkeypatch) -> None:
    scheduler["running"] = True
    calls: list[int] = []
    monkeypatch.setattr(f"{SCHED}.start_daemon", lambda: calls.append(1) or 7)

    result = run("start")

    assert "already running" in result.output
    assert calls == []


def test_start_reports_the_daemon_pid(scheduler) -> None:
    assert run("start").output.strip() == "Cron scheduler started (pid=4242)"


def test_stop_distinguishes_a_real_stop_from_nothing_to_stop(scheduler) -> None:
    assert "stopped" in run("stop").output

    scheduler["stopped"] = False
    assert "is not running" in run("stop").output


# --- status ---------------------------------------------------------------


def test_status_shows_the_pid_only_when_there_is_one(scheduler) -> None:
    out = run("status").output

    assert "Scheduler: running (pid=99)" in out
    assert "Jobs:      2 enabled / 5 total" in out
    assert "Log:       /tmp/cron.log" in out

    scheduler["status"] = {"running": False, "pid": None, "enabled_jobs": 0, "total_jobs": 0, "log_file": "/none"}
    stopped = run("status").output

    assert "Scheduler: stopped" in stopped
    assert "(" not in stopped.splitlines()[0]


# --- list -----------------------------------------------------------------


def test_an_empty_job_list_says_so(scheduler) -> None:
    assert run("list").output.strip() == "No cron jobs configured."


def test_a_job_is_rendered_with_schedule_timezone_payload_and_notify(scheduler) -> None:
    scheduler["jobs"] = [
        {
            "name": "nightly",
            "enabled": True,
            "schedule": "0 3 * * *",
            "timezone": "Asia/Shanghai",
            "command": "pytest -q",
            "payload": {"kind": "command", "channel": "feishu", "to": "ou_1"},
            "notify": {"type": "dm", "user_open_id": "ou_owner"},
            "last_run": "2026-10-24T03:00:00.123456",
            "last_status": "success",
            "next_run": "2026-10-25T03:00:00.123456",
        }
    ]

    out = run("list").output

    assert "  [on ] nightly  0 3 * * * (Asia/Shanghai)" in out
    assert "        cmd: pytest -q" in out
    assert "        payload: command -> feishu:ou_1" in out
    assert "        notify: dm -> ou_owner" in out
    # timestamps are cut to second precision
    assert "last: 2026-10-24T03:00:00 [success]  next: 2026-10-25T03:00:00" in out


def test_a_minimal_job_falls_back_without_inventing_values(scheduler) -> None:
    scheduler["jobs"] = [{"name": "bare", "payload": "not-a-dict", "notify": "not-a-dict", "last_run": "never"}]

    out = run("list").output

    assert "  [on ] bare  ?" in out
    assert "cmd: (agent_turn)" in out
    assert "payload:" not in out
    assert "notify:" not in out
    assert "last: never  next: n/a" in out


def test_a_disabled_job_and_an_open_id_style_notify(scheduler) -> None:
    scheduler["jobs"] = [
        {"name": "off", "enabled": False, "notify": {"type": "group", "chat_id": "oc_1"}},
        {"name": "alt", "notify": {"type": "dm", "open_id": "ou_2"}},
    ]

    out = run("list").output

    assert "  [off] off" in out
    assert "notify: group -> oc_1" in out
    assert "notify: dm -> ou_2" in out


# --- toggle ---------------------------------------------------------------


def test_toggling_a_missing_job_exits_non_zero(scheduler) -> None:
    scheduler["set_enabled_result"] = False

    result = run("toggle", "ghost", "true")

    assert result.exit_code == 1
    assert "not found: ghost" in result.output


def test_toggling_reports_the_new_state(scheduler) -> None:
    assert "is now disabled" in run("toggle", "nightly", "false").output


# --- history --------------------------------------------------------------


def test_empty_history_is_reported_without_error(scheduler) -> None:
    assert run("history").output.strip() == "No execution history."


def test_a_successful_run_does_not_spill_its_stderr(scheduler) -> None:
    scheduler["history"] = [
        {"started_at": "2026-10-24T03:00:00.999999", "name": "nightly", "status": "success", "returncode": 0, "stderr": "noise\nmore"}
    ]

    out = run("history").output

    assert "2026-10-24T03:00:00  nightly  success (rc=0)" in out
    assert "stderr" not in out


def test_a_failed_run_shows_at_most_three_stderr_lines(scheduler) -> None:
    scheduler["history"] = [
        {"started_at": "t", "name": "nightly", "status": "failed", "returncode": 1, "stderr": "a\nb\nc\nd"},
        {"name": "untimed", "status": "failed"},
    ]

    out = run("history").output

    assert out.count("stderr:") == 3, out
    # a missing timestamp prints "?"; a missing returncode prints "rc=?"
    assert "  ?  untimed  failed (rc=?)" in out, out


def test_history_forwards_the_limit_and_the_job_filter(scheduler) -> None:
    """The flags are only decorations until the loader actually receives them."""
    run("history", "nightly", "--limit", "3")

    assert scheduler["history_calls"] == [{"limit": 3, "job_name": "nightly"}]


# --- logs -----------------------------------------------------------------


def test_missing_log_points_at_the_command_that_creates_it(scheduler, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("questorharness.platform.paths.get_logs_dir", lambda: tmp_path)

    assert "oh cron start" in run("logs").output


def test_the_log_tail_is_limited_from_the_end(scheduler, monkeypatch, tmp_path) -> None:
    log = tmp_path / "cron_scheduler.log"
    log.write_text("l1\nl2\nl3\n", encoding="utf-8")
    monkeypatch.setattr("questorharness.platform.paths.get_logs_dir", lambda: tmp_path)

    assert run("logs", "--lines", "2").output.splitlines() == ["l2", "l3"]


def test_the_command_group_is_registered_under_the_app() -> None:
    assert cron_app.info.name == "cron"
    assert cron_app.info.help == "Manage cron scheduler and jobs"
    assert {command.name for command in cron_app.registered_commands} == {
        "start",
        "stop",
        "status",
        "list",
        "toggle",
        "history",
        "logs",
    }
    assert cron_commands.cron_app is cron_app
