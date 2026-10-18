"""P8 T6a：`delegate` 工具契约单测（用假 spawner，不起真 loop）。

证明工具只经 ``ToolContext.spawn_subagent`` 端口委派、把 SpawnResult 映成有界 ToolResult，
未接线/被拒/空目标都 fail-soft 出声不抛（C8/C10；ADR-0038）。
"""

from __future__ import annotations

from pathlib import Path

from questor.capabilities.subagent.delegate import DelegateTool
from questor.contracts.common import JsonObject
from questor.contracts.subagent import SpawnResult


class _FakeCtx:
    """实现 delegate 所需的最小 ctx 面（workspace + spawn_subagent）。"""

    def __init__(self, outcome: SpawnResult | None) -> None:
        self.workspace_root = Path(".")
        self.cwd = Path(".")
        self.tool_call_id = "tc"
        self.calls: list[tuple[str, str | None]] = []
        self._outcome = outcome

    def is_cancelled(self) -> bool:
        return False

    async def spawn_subagent(self, objective: str, *, requested_mode: str | None = None, extra_deny: tuple[str, ...] = ()) -> SpawnResult:
        self.calls.append((objective, requested_mode))
        assert self._outcome is not None
        return self._outcome


class _NoSpawnCtx:
    workspace_root = Path(".")
    cwd = Path(".")
    tool_call_id = "tc"

    def is_cancelled(self) -> bool:
        return False


async def _run(args: JsonObject, ctx: object):
    return await DelegateTool().execute(args, ctx)  # type: ignore[arg-type]


async def test_delegate_success_maps_bounded_summary():
    outcome = SpawnResult(accepted=True, child_run_id="r-child", terminal_status="completed", result="the answer")
    ctx = _FakeCtx(outcome)
    res = await _run({"objective": "do the thing", "mode": "default"}, ctx)
    assert res.status == "success"
    assert ctx.calls == [("do the thing", "default")]
    assert "completed" in (res.result or "") and "the answer" in (res.result or "")
    assert "r-child" in (res.display or "")


async def test_delegate_without_spawner_is_soft_error():
    res = await _run({"objective": "x"}, _NoSpawnCtx())
    assert res.status == "error"
    assert "not available" in (res.result or "")


async def test_delegate_refused_by_gate():
    outcome = SpawnResult(accepted=False, reason="fanout_exceeded")
    res = await _run({"objective": "x"}, _FakeCtx(outcome))
    assert res.status == "error"
    assert "fanout_exceeded" in (res.result or "")


async def test_delegate_empty_objective_rejected():
    res = await _run({"objective": "   "}, _FakeCtx(SpawnResult(accepted=True)))
    assert res.status == "error"
    assert "objective" in (res.result or "")
