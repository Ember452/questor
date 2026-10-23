"""Tool for deleting teams."""

from __future__ import annotations

from pydantic import BaseModel, Field

from questorharness.capabilities.tools.base import BaseTool, ToolExecutionContext, ToolResult


class TeamDeleteToolInput(BaseModel):
    """Arguments for deleting a team."""

    name: str = Field(description="Team name")


class TeamDeleteTool(BaseTool):
    """Delete an in-memory team."""

    name = "team_delete"
    description = "Delete an in-memory team."
    input_model = TeamDeleteToolInput

    async def execute(self, arguments: TeamDeleteToolInput, context: ToolExecutionContext) -> ToolResult:
        if context.subagents is None:
            return ToolResult(output="subagent runtime unavailable", is_error=True)
        try:
            context.subagents.delete_team(arguments.name)
        except ValueError as exc:
            return ToolResult(output=str(exc), is_error=True)
        return ToolResult(output=f"Deleted team {arguments.name}")
