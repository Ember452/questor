"""QuestorHarness sandbox integration helpers."""

from questorharness.providers.sandbox.adapter import (
    SandboxAvailability,
    SandboxUnavailableError,
    build_sandbox_runtime_config,
    get_sandbox_availability,
    wrap_command_for_sandbox,
)
from questorharness.providers.sandbox.docker_backend import DockerSandboxSession, get_docker_availability
from questorharness.providers.sandbox.path_validator import validate_sandbox_path
from questorharness.providers.sandbox.session import (
    get_docker_sandbox,
    is_docker_sandbox_active,
    start_docker_sandbox,
    stop_docker_sandbox,
)

__all__ = [
    "DockerSandboxSession",
    "SandboxAvailability",
    "SandboxUnavailableError",
    "build_sandbox_runtime_config",
    "get_docker_availability",
    "get_docker_sandbox",
    "get_sandbox_availability",
    "is_docker_sandbox_active",
    "start_docker_sandbox",
    "stop_docker_sandbox",
    "validate_sandbox_path",
    "wrap_command_for_sandbox",
]

# questor: allow R5 -- until W8 public-face split
