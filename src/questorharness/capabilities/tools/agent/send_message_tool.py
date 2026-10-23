"""Tool for writing messages to running agent tasks."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from questorharness.capabilities.tools.base import ToolCapabilities, BaseTool, ToolExecutionContext, ToolResult

logger = logging.getLogger(__name__)


class SendMessageToolInput(BaseModel):
    """Arguments for sending a follow-up message to a task."""

    task_id: str = Field(description="Target local agent task id or swarm agent_id (name@team)")
    message: str = Field(description="Message to write to the task stdin")


class SendMessageTool(BaseTool):
    """Send a message to a running local agent task."""

    name = "send_message"
    description = "Send a follow-up message to a running local agent task."
    input_model = SendMessageToolInput

    capabilities = ToolCapabilities(
        artifact_keys=("to", "task_id"),
        remember_as="async_message",
    )

    async def execute(self, arguments: SendMessageToolInput, context: ToolExecutionContext) -> ToolResult:
        # 群协作 Agent 使用 agent_id 格式（name@team）；旧任务使用普通 task ID
        if "@" in arguments.task_id:
            return await self._send_swarm_message(arguments.task_id, arguments.message, context)
        if context.tasks is None:
            return ToolResult(output="task runtime unavailable", is_error=True)
        try:
            await context.tasks.write_to_task(arguments.task_id, arguments.message)
        except ValueError as exc:
            return ToolResult(output=str(exc), is_error=True)
        return ToolResult(output=f"Sent message to task {arguments.task_id}")

    async def _send_swarm_message(
        self,
        agent_id: str,
        message: str,
        context: ToolExecutionContext,
    ) -> ToolResult:
        """Route a message to a swarm agent via the injected runtime."""
        subagents = context.subagents
        if subagents is None:
            return ToolResult(output="subagent runtime unavailable", is_error=True)
        try:
            await subagents.send_message(agent_id, text=message)
        except ValueError as exc:
            return ToolResult(output=str(exc), is_error=True)
        except Exception as exc:
            logger.error("Failed to send message to %s: %s", agent_id, exc)
            return ToolResult(output=str(exc), is_error=True)
        return ToolResult(output=f"Sent message to agent {agent_id}")

# questor: allow R7 -- until W8 adds the mirror test
