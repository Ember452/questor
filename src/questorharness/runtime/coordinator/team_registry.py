"""In-memory team registry used by coordinator mode."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TeamRecord:
    """A lightweight in-memory team."""

    name: str
    description: str = ""
    agents: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


class TeamRegistry:
    """Store teams and agent memberships."""

    def __init__(self) -> None:
        self._teams: dict[str, TeamRecord] = {}

    def create_team(self, name: str, description: str = "") -> TeamRecord:
        if name in self._teams:
            raise ValueError(f"Team '{name}' already exists")
        team = TeamRecord(name=name, description=description)
        self._teams[name] = team
        return team

    def delete_team(self, name: str) -> None:
        if name not in self._teams:
            raise ValueError(f"Team '{name}' does not exist")
        del self._teams[name]

    def add_agent(self, team_name: str, task_id: str) -> None:
        team = self._require_team(team_name)
        if task_id not in team.agents:
            team.agents.append(task_id)

    def send_message(self, team_name: str, message: str) -> None:
        self._require_team(team_name).messages.append(message)

    def list_teams(self) -> list[TeamRecord]:
        return sorted(self._teams.values(), key=lambda item: item.name)

    def _require_team(self, name: str) -> TeamRecord:
        team = self._teams.get(name)
        if team is None:
            raise ValueError(f"Team '{name}' does not exist")
        return team


_DEFAULT_TEAM_REGISTRY: TeamRegistry | None = None


def get_team_registry() -> TeamRegistry:
    """Return the singleton team registry."""
    global _DEFAULT_TEAM_REGISTRY
    if _DEFAULT_TEAM_REGISTRY is None:
        _DEFAULT_TEAM_REGISTRY = TeamRegistry()
    return _DEFAULT_TEAM_REGISTRY

# questor: allow R7 -- until W8 adds the mirror test
