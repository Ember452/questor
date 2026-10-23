"""Tool for stopping tasks."""

from __future__ import annotations

from pydantic import BaseModel, Field

from questorharness.capabilities.tools.base import BaseTool, ToolExecutionContext, ToolResult


class TaskStopToolInput(BaseModel):
    """Arguments for stopping a task."""

    task_id: str = Field(description="Task identifier")


class TaskStopTool(BaseTool):
    """Stop a background task."""

    name = "task_stop"
    description = "Stop a background task."
    input_model = TaskStopToolInput

    async def execute(self, arguments: TaskStopToolInput, context: ToolExecutionContext) -> ToolResult:
        if context.tasks is None:
            return ToolResult(output="task runtime unavailable", is_error=True)
        try:
            task = await context.tasks.stop_task(arguments.task_id)
        except ValueError as exc:
            return ToolResult(output=str(exc), is_error=True)
        return ToolResult(output=f"Stopped task {task.id}")

# questor: allow R7 -- until W8 adds the mirror test
