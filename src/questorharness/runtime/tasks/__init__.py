"""Task exports."""

from questorharness.runtime.tasks.local_agent_task import spawn_local_agent_task
from questorharness.runtime.tasks.local_shell_task import spawn_shell_task
from questorharness.runtime.tasks.task_manager import BackgroundTaskManager, get_task_manager
from questorharness.runtime.tasks.stop_task import stop_task
from questorharness.contracts.task import TaskRecord, TaskStatus, TaskType

__all__ = [
    "BackgroundTaskManager",
    "TaskRecord",
    "TaskStatus",
    "TaskType",
    "get_task_manager",
    "spawn_local_agent_task",
    "spawn_shell_task",
    "stop_task",
]
