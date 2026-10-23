"""Runtime-side implementations of the ports consumed by capability tools."""

from __future__ import annotations

from collections.abc import Callable

from questorharness.contracts.task import CompletionListener, TaskRecord, TaskStatus, TaskType
from questorharness.runtime.tasks.manager import BackgroundTaskManager, get_task_manager


class DefaultTaskRuntime:
    """Delegate the task port to the process-wide task manager.

    The manager is resolved per call because ``get_task_manager`` recreates it
    when the data directory changes (tests and embedded callers rely on that).
    """

    def __init__(self, manager_provider: Callable[[], BackgroundTaskManager] = get_task_manager) -> None:
        self._manager_provider = manager_provider

    @property
    def _manager(self) -> BackgroundTaskManager:
        return self._manager_provider()

    async def create_shell_task(
        self,
        *,
        command: str | None = None,
        description: str,
        cwd: object,
        task_type: TaskType = "local_bash",
        env: dict[str, str] | None = None,
        argv: list[str] | None = None,
    ) -> TaskRecord:
        return await self._manager.create_shell_task(
            command=command,
            description=description,
            cwd=cwd,
            task_type=task_type,
            env=env,
            argv=argv,
        )

    async def create_agent_task(
        self,
        *,
        prompt: str,
        description: str,
        cwd: object,
        model: str | None = None,
        api_key: str | None = None,
    ) -> TaskRecord:
        return await self._manager.create_agent_task(
            prompt=prompt,
            description=description,
            cwd=cwd,
            model=model,
            api_key=api_key,
        )

    def get_task(self, task_id: str) -> TaskRecord | None:
        return self._manager.get_task(task_id)

    def list_tasks(self, *, status: TaskStatus | None = None) -> list[TaskRecord]:
        return self._manager.list_tasks(status=status)

    def update_task(
        self,
        task_id: str,
        *,
        description: str | None = None,
        progress: int | None = None,
        status_note: str | None = None,
    ) -> TaskRecord:
        return self._manager.update_task(
            task_id,
            description=description,
            progress=progress,
            status_note=status_note,
        )

    async def stop_task(self, task_id: str) -> TaskRecord:
        return await self._manager.stop_task(task_id)

    async def write_to_task(self, task_id: str, data: str) -> None:
        await self._manager.write_to_task(task_id, data)

    def read_task_output(self, task_id: str, *, max_bytes: int = 12000) -> str:
        return self._manager.read_task_output(task_id, max_bytes=max_bytes)

    def register_completion_listener(self, listener: CompletionListener) -> Callable[[], None]:
        return self._manager.register_completion_listener(listener)

# questor: allow R7 -- until W8 adds the mirror test
