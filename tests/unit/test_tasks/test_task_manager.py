"""Mirror test for ``runtime/tasks/task_manager.py`` (plan 01, R7).

Scope note: spawning, restarting and output copying are exercised by
``tests/unit/test_tasks/test_manager.py`` and the task tool tests. This file covers
the part that had no test at all: the registry contract of a fresh manager and the
module-level singleton lifecycle.
"""

from __future__ import annotations

from questorharness.runtime.tasks.task_manager import (
    BackgroundTaskManager,
    get_task_manager,
    reset_task_manager,
)


def test_a_fresh_manager_knows_no_tasks() -> None:
    manager = BackgroundTaskManager()

    assert manager.list_tasks() == []
    assert manager.get_task("missing") is None


def test_list_tasks_accepts_a_status_filter_on_an_empty_registry() -> None:
    manager = BackgroundTaskManager()

    assert manager.list_tasks(status="running") == []


def test_get_task_manager_is_a_singleton_until_reset() -> None:
    reset_task_manager()
    first = get_task_manager()
    assert get_task_manager() is first

    reset_task_manager()
    second = get_task_manager()
    assert second is not first
    assert isinstance(second, BackgroundTaskManager)
    reset_task_manager()


def test_close_leaves_the_registry_empty() -> None:
    manager = BackgroundTaskManager()
    manager.close()

    assert manager.list_tasks() == []
    assert manager.get_task("missing") is None
