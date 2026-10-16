"""A3 DoD —— capability/risk fail-closed：exec/write 无沙箱后端时 被 DENIED。

把权限设为 full_auto 使其*放行*调用；loop 自身的沙箱闸仍须 deny（fail-closed，03 §10 T4）。
以此证明 deny 来自沙箱闸而非权限引擎，且 ``execute`` 从不运行。
"""

from __future__ import annotations

from pathlib import Path

from questor.contracts.common import new_id
from questor.contracts.ports import StreamChunk
from questor.contracts.sandbox import Confinement, SandboxBackend, SandboxDescriptor
from questor.contracts.state_schema import Budget, RunStatus, ToolCallStatus
from questor.contracts.tool import Capability, Risk, Tool, ToolContext, ToolResult, ToolSpec
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.policy.react_policy import ReActPolicy
from questor.providers.fake import ScriptedProvider
from questor.state.domain_state import PermissionCtx, Run


def _full_auto_run() -> Run:
    return Run(run_id=new_id("run"), budget=Budget(max_turns=5), permission_ctx=PermissionCtx(mode="full_auto"))


class _ExecTool(Tool):
    ran = False

    def __init__(self) -> None:
        self.spec = ToolSpec(
            name="bash",
            description="run a shell command",
            params={"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"], "additionalProperties": False},
            capability=Capability.EXEC,
            risk=Risk.HIGH,
            read_only=False,
        )

    def available(self) -> bool:
        return True

    async def execute(self, args, ctx: ToolContext) -> ToolResult:
        type(self).ran = True
        return ToolResult(status="success", result="SHOULD NOT RUN")


def _turn(call_id: str) -> list[StreamChunk]:
    return [
        StreamChunk(kind="tool_call", tool_call={"index": 0, "id": call_id, "name": "bash", "args_delta": '{"command": "ls"}'}),
        StreamChunk(kind="finish", finish_reason="tool_calls"),
    ]


_ANSWER = [StreamChunk(kind="text", text="ok"), StreamChunk(kind="finish", finish_reason="stop")]


async def test_exec_denied_without_sandbox(tmp_path: Path) -> None:
    _ExecTool.ran = False
    tool = _ExecTool()
    loop = DefaultTurnLoop(
        provider=ScriptedProvider([_turn("tc_e"), _ANSWER]),
        policy=ReActPolicy(),
        permission=DefaultPermissionEngine(),  # 模式由 Run.permission_ctx 提供，引擎不保存配置
        bus=InProcessEventBus(None),
        tool_for=lambda name: tool if name == "bash" else None,
        tools=(tool,),
        sandbox=None,  # no backend -> the loop's fail-closed gate must deny
        workspace_root=tmp_path,
    )
    run = await loop.drive(_full_auto_run(), "list files")
    call = next(c for c in run.tool_ledger.calls if c.name == "bash")
    assert call.status is ToolCallStatus.DENIED
    assert "fail-closed" in str(call.result)
    assert _ExecTool.ran is False  # execute never called
    assert run.status is RunStatus.COMPLETED  # loop kept going after the deny


async def test_exec_allowed_with_capable_sandbox(tmp_path: Path) -> None:
    class _GoodSandbox:
        def describe(self) -> SandboxDescriptor:
            return SandboxDescriptor(
                backend=SandboxBackend.SEATBELT,
                confinement=Confinement.FULL,
                fences_writes=True,
                fences_network=True,
                isolates_process_tree=True,
                limitation="full test sandbox",
            )

        def fences_writes(self) -> bool:
            return True

        def fences_network(self) -> bool:
            return True

        def isolates_process_tree(self) -> bool:
            return True

        def wrap_argv(self, capability, argv):  # noqa: ANN001, ANN201
            return argv

    tool = _ExecTool()
    loop = DefaultTurnLoop(
        provider=ScriptedProvider([_turn("tc_e2"), _ANSWER]),
        policy=ReActPolicy(),
        permission=DefaultPermissionEngine(),
        bus=InProcessEventBus(None),
        tool_for=lambda name: tool if name == "bash" else None,
        tools=(tool,),
        sandbox=_GoodSandbox(),  # capable backend -> not denied by the gate
        workspace_root=tmp_path,
    )
    run = await loop.drive(_full_auto_run(), "list files")
    call = next(c for c in run.tool_ledger.calls if c.name == "bash")
    assert call.status is ToolCallStatus.SUCCESS
