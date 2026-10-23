"""Tool for creating teams."""

from __future__ import annotations

from pydantic import BaseModel, Field

from questorharness.capabilities.tools.base import BaseTool, ToolExecutionContext, ToolResult


class TeamCreateToolInput(BaseModel):
    """Arguments for creating a team."""

    name: str = Field(description="Team name")
    description: str = Field(default="", description="Team description")


class TeamCreateTool(BaseTool):
    """Create an in-memory team."""

    name = "team_create"
    description = "Create a lightweight in-memory team for agent tasks."
    input_model = TeamCreateToolInput

    async def execute(self, arguments: TeamCreateToolInput, context: ToolExecutionContext) -> ToolResult:
        if context.subagents is None:
            return ToolResult(output="subagent runtime unavailable", is_error=True)
        try:
            name = context.subagents.create_team(arguments.name, arguments.description)
        except ValueError as exc:
            return ToolResult(output=str(exc), is_error=True)
        return ToolResult(output=f"Created team {name}")
