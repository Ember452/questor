"""Tool for listing tasks."""

from __future__ import annotations

from pydantic import BaseModel, Field

from questorharness.capabilities.tools.base import BaseTool, ToolExecutionContext, ToolResult


class TaskListToolInput(BaseModel):
    """Arguments for task listing."""

    status: str | None = Field(default=None, description="Optional status filter")


class TaskListTool(BaseTool):
    """List background tasks."""

    name = "task_list"
    description = "List background tasks."
    input_model = TaskListToolInput

    def is_read_only(self, arguments: TaskListToolInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: TaskListToolInput, context: ToolExecutionContext) -> ToolResult:
        if context.tasks is None:
            return ToolResult(output="task runtime unavailable", is_error=True)
        tasks = context.tasks.list_tasks(status=arguments.status)  # type: ignore[arg-type]
        if not tasks:
            return ToolResult(output="(no tasks)")
        return ToolResult(
            output="\n".join(f"{task.id} {task.type} {task.status} {task.description}" for task in tasks)
        )
