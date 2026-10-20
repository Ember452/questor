"""L3 委派工具：把一个子任务交给独立子 agent Run 完成并取回有界结果（design/00 L3；ADR-0038）。

工具是"能力"不是"写者"：它拿不到 registry/bus 裸句柄，只经 ``ToolContext.spawn_subagent``（Harness 注入的
端口）发起委派；权限/超时/记账由 Harness 在外层包裹（C8）。子 run 的权限由端口投影自父（⊆父，ADR-0040）。
未接线（单 run 场景）时 fail-soft 返回 error，不抛、不崩循环。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from questor.contracts.profile import PERMISSION_MODES
from questor.contracts.tool import Capability, Risk, Tool, ToolResult, ToolSpec

if TYPE_CHECKING:
    from questor.contracts.tool import ToolContext

#: delegate 回给模型的摘要上限（C18/ADR-0019：正文有界，绝不含无界载荷）。
_MAX_DELEGATE_RESULT_CHARS = 4096


class DelegateTool(Tool):
    """`delegate(objective, mode?)` → 起一个子 agent Run 协作、等其终态、回上有界摘要。"""

    def __init__(self) -> None:
        self.spec = ToolSpec(
            name="delegate",
            description="Delegate a self-contained sub-task to a child agent run and await its result.",
            params={
                "type": "object",
                "properties": {
                    "objective": {"type": "string", "description": "Short, self-contained sub-task goal."},
                    "mode": {
                        "type": "string",
                        # 枚举取自 L0 ``contracts.profile.PERMISSION_MODES``（OPT-3 c4）：顺序即协议顺序，
                        # 参与 ProviderRequest.tools 的字节形态，不得重排。
                        "enum": list(PERMISSION_MODES),
                        "description": "Requested child permission mode (clamped to ≤ parent).",
                    },
                    "wait": {"type": "boolean", "description": "true (default): block until the child reaches a terminal state and return its result; false: fire-and-forget and return immediately."},
                },
                "required": ["objective"],
            },
            capability=Capability.READONLY,
            risk=Risk.LOW,
            read_only=False,
            # ADR-0029 的 orchestrator gate 在 P8 由 SubagentSpawnerPort 的 fan-out admission 落实现。
            orchestrator=True,
        )

    def available(self) -> bool:
        return True

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:  # noqa: ANN001
        objective = args.get("objective") if isinstance(args, dict) else None
        if not isinstance(objective, str) or not objective.strip():
            return ToolResult(status="error", result="delegate requires a non-empty 'objective' string")
        spawn = getattr(ctx, "spawn_subagent", None)
        if spawn is None:
            # 未接 spawner 的 run：明确出声、不崩（fail-soft，design/04 L1）。
            return ToolResult(status="error", result="subagent orchestration is not available for this run")
        requested_mode = args.get("mode") if isinstance(args, dict) else None
        wait = args.get("wait", True) if isinstance(args, dict) else True
        outcome = await spawn(objective.strip(), requested_mode=requested_mode, wait=bool(wait))
        if not outcome.accepted:
            return ToolResult(status="error", display="delegation refused", result=f"delegate refused: {outcome.reason}")
        if outcome.terminal_status is None:
            # fire-and-forget：子仍在跑，仅回报已发起（不带结果摘要）。
            return ToolResult(status="success", result=f"delegated to subagent {outcome.child_run_id} (running)", display=f"delegated → child {outcome.child_run_id}")
        summary = (outcome.result or "")[:_MAX_DELEGATE_RESULT_CHARS]
        display = f"delegated → child {outcome.child_run_id} [{outcome.terminal_status}]"
        return ToolResult(status="success", result=f"subagent {outcome.terminal_status}: {summary}".strip(), display=display)
