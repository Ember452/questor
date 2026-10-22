from __future__ import annotations

import pytest

from questorharness.capabilities.schedule import cron_scheduler


@pytest.mark.asyncio
async def test_cron_notification_dispatches_to_registered_handler(monkeypatch):
    calls = []

    async def handler(job, entry, notify, content):
        calls.append((job, entry, notify, content))

    monkeypatch.setattr(cron_scheduler, "_load_notification_handlers", lambda: None)
    monkeypatch.setitem(cron_scheduler._NOTIFICATION_HANDLERS, "test", handler)
    job = {"name": "nightly", "command": "echo ok", "notify": {"type": "test"}}
    entry = {"started_at": "start", "ended_at": "end", "stdout": "ok"}

    await cron_scheduler._notify_job_result(job, entry)

    assert entry["notification_status"] == "sent"
    assert len(calls) == 1
    assert "Cron job finished: nightly" in calls[0][3]


@pytest.mark.asyncio
async def test_cron_notification_unknown_type_marks_failed(monkeypatch):
    monkeypatch.setattr(cron_scheduler, "_load_notification_handlers", lambda: None)
    job = {"name": "nightly", "command": "echo ok", "notify": {"type": "missing"}}
    entry = {"started_at": "start", "ended_at": "end"}

    await cron_scheduler._notify_job_result(job, entry)

    assert entry["notification_status"] == "failed"
    assert "unsupported notify.type: missing" in entry["notification_error"]
