"""Tool for retrieving task details."""

from __future__ import annotations

from pydantic import BaseModel, Field

from questorharness.capabilities.tools.base import ToolCapabilities, BaseTool, ToolExecutionContext, ToolResult


class TaskGetToolInput(BaseModel):
    """Arguments for task lookup."""

    task_id: str = Field(description="Task identifier")


class TaskGetTool(BaseTool):
    """Return detailed task state."""

    name = "task_get"
    description = "Get details for a background task."
    input_model = TaskGetToolInput

    capabilities = ToolCapabilities(
        read_only_by_default=True,
    )

    def is_read_only(self, arguments: TaskGetToolInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: TaskGetToolInput, context: ToolExecutionContext) -> ToolResult:
        if context.tasks is None:
            return ToolResult(output="task runtime unavailable", is_error=True)
        task = context.tasks.get_task(arguments.task_id)
        if task is None:
            return ToolResult(output=f"No task found with ID: {arguments.task_id}", is_error=True)
        return ToolResult(output=str(task))

# questor: allow R7 -- until W8 adds the mirror test
