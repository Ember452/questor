"""Sandbox runtime adapter implementing the tool-facing port."""

from __future__ import annotations

from pathlib import Path

from questorharness.providers.sandbox.path_validator import validate_sandbox_path
from questorharness.providers.sandbox.session import get_docker_sandbox, is_docker_sandbox_active


class ProviderSandboxRuntime:
    """Adapter over the provider-level sandbox helpers."""

    def is_active(self) -> bool:
        return is_docker_sandbox_active()

    def validate_path(self, path: Path, cwd: Path) -> tuple[bool, str]:
        return validate_sandbox_path(path, cwd)

    def session(self):
        return get_docker_sandbox()

# questor: allow R7 -- until W8 adds the mirror test
