"""P2 ToolSpec/ToolContext/Budget contracts。"""

from __future__ import annotations

from pathlib import Path

import pytest

from questor.contracts.state_schema import Budget
from questor.contracts.tool import Capability, Risk, ToolContext, ToolSpec


def _spec(**overrides):  # noqa: ANN003, ANN202
    values = {
        "name": "write",
        "description": "write a text file inside the workspace",
        "params": {"type": "object"},
        "capability": Capability.WRITE,
        "risk": Risk.MEDIUM,
        "read_only": False,
    }
    values.update(overrides)
    return ToolSpec(**values)


def test_tool_spec_timeout_defaults_and_validation() -> None:
    assert _spec().timeout_s is None
    assert _spec(timeout_s=30).timeout_s == 30
    with pytest.raises(ValueError, match="positive"):
        _spec(timeout_s=0)


def test_budget_has_fail_closed_timeout_defaults() -> None:
    budget = Budget()
    assert budget.approval_timeout_seconds == 300
    assert budget.tool_default_timeout_seconds == 120
    with pytest.raises(ValueError, match="approval_timeout"):
        Budget(approval_timeout_seconds=0)


def test_tool_context_protocol_requires_harness_seams() -> None:
    class _Ctx:
        tool_call_id = "tc"
        workspace_root = Path(".")
        cwd = Path(".")

        def is_cancelled(self) -> bool:
            return False

        def report_progress(self, message: str) -> None:
            pass

        def emit_progress(self, payload: dict) -> None:
            pass

        def declare_env_passthrough(self, name: str) -> None:
            pass

        async def run_process(self, request) -> object:  # noqa: ANN001
            return object()

        async def put_artifact(self, content, *, kind, media_type="text/plain") -> object:  # noqa: ANN001
            return object()

        async def memory_search(self, query, *, k=8, scope=None):  # noqa: ANN001
            return ()

    assert isinstance(_Ctx(), ToolContext)
