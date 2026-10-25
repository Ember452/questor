"""Subagent port backed by agent definitions, swarm backends and teams."""

from __future__ import annotations

from typing import Literal, cast

from questorharness.contracts.agent import AgentProfile
from questorharness.contracts.subagent import SpawnResult, TeammateMessage
from questorharness.runtime.coordinator.agent_definitions import get_agent_definition
from questorharness.runtime.coordinator.coordinator_mode import get_team_registry
from questorharness.runtime.swarm.registry import get_backend_registry
from questorharness.runtime.swarm.models import TeammateSpawnConfig

_SUBPROCESS_BACKEND = "subprocess"
_SpawnTaskType = Literal["local_agent", "remote_agent", "in_process_teammate"]


class DefaultSubagentRuntime:
    """Resolve agent profiles and drive the subprocess swarm backend."""

    def resolve_profile(self, name: str) -> AgentProfile | None:
        definition = get_agent_definition(name)
        if definition is None:
            return None
        return AgentProfile(
            name=definition.name,
            model=definition.model,
            system_prompt=definition.system_prompt,
            permissions=list(definition.permissions),
            tools=list(definition.tools) if definition.tools else None,
            disallowed_tools=(
                list(definition.disallowed_tools) if definition.disallowed_tools else None
            ),
        )

    async def spawn(
        self,
        *,
        name: str,
        team: str,
        prompt: str,
        cwd: str,
        model: str | None = None,
        command: str | None = None,
        system_prompt: str | None = None,
        permissions: list[str] | None = None,
        allowed_tools: list[str] | None = None,
        disallowed_tools: list[str] | None = None,
        task_type: str = "local_agent",
    ) -> SpawnResult:
        executor = get_backend_registry().get_executor(_SUBPROCESS_BACKEND)
        config = TeammateSpawnConfig(
            name=name,
            team=team,
            prompt=prompt,
            cwd=cwd,
            parent_session_id="main",
            model=model,
            command=command,
            system_prompt=system_prompt,
            permissions=list(permissions or []),
            allowed_tools=list(allowed_tools) if allowed_tools else None,
            disallowed_tools=list(disallowed_tools) if disallowed_tools else None,
            task_type=cast(_SpawnTaskType, task_type),
        )
        return await executor.spawn(config)

    async def send_message(self, agent_id: str, *, text: str, from_agent: str = "coordinator") -> None:
        executor = get_backend_registry().get_executor(_SUBPROCESS_BACKEND)
        await executor.send_message(agent_id, TeammateMessage(text=text, from_agent=from_agent))

    def create_team(self, name: str, description: str = "") -> str:
        return get_team_registry().create_team(name, description).name

    def delete_team(self, name: str) -> None:
        get_team_registry().delete_team(name)

    def attach_agent(self, team: str, task_id: str) -> None:
        registry = get_team_registry()
        try:
            registry.add_agent(team, task_id)
        except ValueError:
            registry.create_team(team)
            registry.add_agent(team, task_id)

# questor: allow R7 -- until W8 adds the mirror test
