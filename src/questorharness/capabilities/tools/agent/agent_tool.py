"""Tool for spawning local agent tasks."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from questorharness.contracts.agent import AgentProfile
from questorharness.contracts.hooks import HookEvent
from questorharness.contracts.task import TaskRecord
from questorharness.capabilities.tools.contract import ToolCapabilities, BaseTool, ToolExecutionContext, ToolResult

logger = logging.getLogger(__name__)


def _tool_surface(profile: AgentProfile | None) -> tuple[list[str] | None, list[str] | None]:
    """从 agent 定义取出（白名单，黑名单）；未声明一律 None（继承全部）。"""
    if profile is None:
        return None, None
    return (
        list(profile.tools) if profile.tools else None,
        list(profile.disallowed_tools) if profile.disallowed_tools else None,
    )


class AgentToolInput(BaseModel):
    """Arguments for local agent spawning."""

    description: str = Field(description="Short description of the delegated work")
    prompt: str = Field(description="Full prompt for the local agent")
    subagent_type: str | None = Field(
        default=None,
        description="Agent type for definition lookup (e.g. 'general-purpose', 'Explore', 'worker')",
    )
    model: str | None = Field(default=None)
    command: str | None = Field(default=None, description="Override spawn command")
    team: str | None = Field(default=None, description="Optional team to attach the agent to")
    mode: str = Field(
        default="local_agent",
        description="Agent mode: local_agent, remote_agent, or in_process_teammate",
    )


class AgentTool(BaseTool):
    """Spawn a local agent subprocess."""

    name = "agent"
    description = "Spawn a local background agent task."
    input_model = AgentToolInput

    capabilities = ToolCapabilities(
        artifact_keys=("description", "prompt"),
        remember_as="async_agent",
    )

    async def execute(self, arguments: AgentToolInput, context: ToolExecutionContext) -> ToolResult:
        if arguments.mode not in {"local_agent", "remote_agent", "in_process_teammate"}:
            return ToolResult(
                output="Invalid mode. Use local_agent, remote_agent, or in_process_teammate.",
                is_error=True,
            )

        # 若指定 subagent_type 则查找 Agent 定义
        subagents = context.subagents
        if subagents is None:
            return ToolResult(output="subagent runtime unavailable", is_error=True)
        tasks = context.tasks
        profile = subagents.resolve_profile(arguments.subagent_type) if arguments.subagent_type else None
        allowed_tools, disallowed_tools = _tool_surface(profile)

        # 为群协作后端解析团队和 Agent 名称
        team = arguments.team or "default"
        agent_name = arguments.subagent_type or "agent"

        # 任务状态由注入的 TaskRuntime 统一持有，agent 任务因此可被任务工具轮询。
        try:
            result = await subagents.spawn(
                name=agent_name,
                team=team,
                prompt=arguments.prompt,
                cwd=str(context.cwd),
                model=arguments.model or (profile.model if profile else None),
                command=arguments.command,
                system_prompt=profile.system_prompt if profile else None,
                permissions=list(profile.permissions) if profile else [],
                allowed_tools=allowed_tools,
                disallowed_tools=disallowed_tools,
                task_type=arguments.mode,
            )
        except Exception as exc:
            logger.error("Failed to spawn agent: %s", exc)
            return ToolResult(output=str(exc), is_error=True)

        if not result.success:
            return ToolResult(output=result.error or "Failed to spawn agent", is_error=True)

        if arguments.team:
            subagents.attach_agent(arguments.team, result.task_id)

        if context.hook_executor is not None and tasks is not None:
            unregister = None

            async def _emit_subagent_stop(task_record: TaskRecord) -> None:
                nonlocal unregister
                if task_record.id != result.task_id:
                    return
                if unregister is not None:
                    unregister()
                    unregister = None
                await context.hook_executor.execute(
                    HookEvent.SUBAGENT_STOP,
                    {
                        "event": HookEvent.SUBAGENT_STOP.value,
                        "agent_id": result.agent_id,
                        "task_id": result.task_id,
                        "backend_type": result.backend_type,
                        "status": task_record.status,
                        "return_code": task_record.return_code,
                        "description": arguments.description,
                        "subagent_type": arguments.subagent_type or "agent",
                        "team": team,
                        "mode": arguments.mode,
                    },
                )

            unregister = tasks.register_completion_listener(_emit_subagent_stop)
            task_record = tasks.get_task(result.task_id)
            if task_record is not None and task_record.status in {"completed", "failed", "killed"}:
                await _emit_subagent_stop(task_record)

        return ToolResult(
            output=(
                f"Spawned agent {result.agent_id} "
                f"(task_id={result.task_id}, backend={result.backend_type})"
            ),
            metadata={
                "agent_id": result.agent_id,
                "task_id": result.task_id,
                "backend_type": result.backend_type,
                "description": arguments.description,
            },
        )

# questor: allow R7 -- until W8 adds the mirror test
