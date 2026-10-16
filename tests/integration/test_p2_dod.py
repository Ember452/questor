"""T21：P2 端到端 DoD —— 真实 loop + PermissionCtx 引擎 + capability floor + registry + inbox。

用一个"全接线"的 DefaultTurnLoop（真实权限引擎、真实沙箱 descriptor、真实/注册工具面、
Command Inbox）验证 §5.1 的头部判据不是各单元各自绿，而是合起来真跑：
危险写触发 ask、答 n 拒绝且 run 续跑、答 y 执行；full_auto 不能越过能力下限；
敏感路径 deny；非法参数在 execute 前被拒；Windows 真机 powershell 删除需审批。
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

import pytest

from questor.capabilities.tools.apply_patch import ApplyPatchTool
from questor.capabilities.tools.edit import EditTool
from questor.capabilities.tools.powershell import PowerShellTool
from questor.capabilities.tools.read import ReadTool
from questor.capabilities.tools.registry import ToolRegistry
from questor.capabilities.tools.write import WriteTool
from questor.contracts.common import new_id
from questor.contracts.events import ResolveApproval, SubmitMessage
from questor.contracts.ports import StreamChunk
from questor.contracts.state_schema import Budget, ContentBlock, Message, Role, RunStatus, ToolCallStatus
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.kernel.run_control import RunController
from questor.policy.react_policy import ReActPolicy
from questor.providers.fake import ScriptedProvider
from questor.providers.process_runner import SandboxedProcessRunner
from questor.providers.sandbox import NullSandbox, WindowsJobSandbox
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import PermissionCtx, Run


def _surface(*tools) -> tuple:  # noqa: ANN002
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry, registry.freeze_for_run("frozen")


def _wired(tmp_path: Path, provider, bus, store, sandbox, process_runner=None) -> DefaultTurnLoop:
    _registry, surface = _surface(ReadTool(), WriteTool(), EditTool(), ApplyPatchTool(), PowerShellTool())
    return DefaultTurnLoop(
        provider=provider,
        policy=ReActPolicy(),
        permission=DefaultPermissionEngine(),
        bus=bus,
        tool_for=surface.tool_for,
        tools=surface.tools,
        surface=surface,
        sandbox=sandbox,
        process_runner=process_runner,
        store=store,
        workspace_root=tmp_path,
    )


def _submit_user(controller: RunController, text: str) -> None:
    msg = Message(id=new_id("msg"), role=Role.USER, content=(ContentBlock(type="text", text=text),), seq=0)
    return controller.submit(SubmitMessage(run_id=controller.run.run_id, content=msg), source="dod", idempotency_key=f"submit:{controller.run.run_id}")


def _write_turn(tool: str, args_json: str, call_id: str = "tc1") -> list[StreamChunk]:
    return [
        StreamChunk(kind="tool_call", tool_call={"index": 0, "id": call_id, "name": tool, "args_delta": args_json}),
        StreamChunk(kind="finish", finish_reason="tool_calls"),
    ]


_ANSWER = [StreamChunk(kind="text", text="done"), StreamChunk(kind="finish", finish_reason="stop")]


async def _drive_with_decision(tmp_path: Path, turns, decision: str | None, *, sandbox, mode: str = "default", process_runner=None) -> tuple:
    """全接线跑一轮；decision=None 表示不外部审批（走引擎即时 deny/allow 或超时）。"""
    store = await SQLiteStore(":memory:").connect()
    bus = InProcessEventBus(store)
    provider = ScriptedProvider(turns)
    loop = _wired(tmp_path, provider, bus, store, sandbox, process_runner)
    controller = RunController(Run(run_id=new_id("run"), budget=Budget(max_turns=4, approval_timeout_seconds=5), permission_ctx=PermissionCtx(mode=mode, workspace_root=str(tmp_path), cwd=str(tmp_path))))
    # loop 需要绑定到同一个 controller.run；drive_controller 用 controller 里的 run。
    await _submit_user(controller, "go")
    if decision is not None:
        async def approver() -> None:
            async for event in bus.subscribe(controller.run.run_id, 0):
                if event.type == "approval_request":
                    await controller.submit(
                        ResolveApproval(run_id=controller.run.run_id, request_id=event.data["request_id"], decision=decision, decided_by="dod"),
                        source="dod",
                        idempotency_key=event.data["request_id"],
                    )
                    return

        task = asyncio.create_task(approver())
        run = await loop.drive_controller(controller)
        await task
    else:
        run = await loop.drive_controller(controller)
    await store.close()
    return run


async def test_dod_write_asks_then_allow_executes(tmp_path: Path) -> None:
    turns = [_write_turn("write", '{"file_path": "out.txt", "content": "hi"}'), _ANSWER]
    run = await _drive_with_decision(tmp_path, turns, "allow", sandbox=NullSandbox())
    call = next(c for c in run.tool_ledger.calls if c.tool_call_id == "tc1")
    assert call.status is ToolCallStatus.SUCCESS
    assert run.status is RunStatus.COMPLETED
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "hi"


async def test_dod_write_asks_then_deny_continues(tmp_path: Path) -> None:
    turns = [_write_turn("write", '{"file_path": "nope.txt", "content": "x"}'), _ANSWER]
    run = await _drive_with_decision(tmp_path, turns, "deny", sandbox=NullSandbox())
    call = next(c for c in run.tool_ledger.calls if c.tool_call_id == "tc1")
    assert call.status is ToolCallStatus.DENIED
    assert run.status is RunStatus.COMPLETED  # 拒绝不崩 run，继续到终态
    assert not (tmp_path / "nope.txt").exists()


async def test_dod_full_auto_cannot_bypass_exec_floor(tmp_path: Path) -> None:
    # NullSandbox（none）下任何 exec 都被能力下限直接 deny，full_auto 也不例外。
    turns = [_write_turn("powershell", '{"command": "Get-ChildItem"}'), _ANSWER]
    run = await _drive_with_decision(tmp_path, turns, None, sandbox=NullSandbox(), mode="full_auto")
    call = next(c for c in run.tool_ledger.calls if c.tool_call_id == "tc1")
    assert call.status is ToolCallStatus.DENIED
    reason = (call.permission_reason or call.result or "").lower()
    assert "floor" in reason or "sandbox" in reason  # 能力下限拒绝，full_auto 不能降 allow


async def test_dod_sensitive_path_denied_under_full_auto(tmp_path: Path) -> None:
    # 写 workspace 内的 .env：敏感路径在 floor/mode 之前 deny，且不产生审批请求（不可越）。
    turns = [_write_turn("write", '{"file_path": ".env", "content": "SECRET=1"}'), _ANSWER]
    run = await _drive_with_decision(tmp_path, turns, None, sandbox=NullSandbox(), mode="full_auto")
    call = next(c for c in run.tool_ledger.calls if c.tool_call_id == "tc1")
    assert call.status is ToolCallStatus.DENIED
    assert not (tmp_path / ".env").exists()
    assert run.permission_ctx.approvals == ()  # 即时拒绝，未走 ask


async def test_dod_invalid_json_rejected_before_execute(tmp_path: Path) -> None:
    turns = [_write_turn("write", "{not valid json", call_id="tcbad"), _ANSWER]
    run = await _drive_with_decision(tmp_path, turns, None, sandbox=NullSandbox())
    call = next(c for c in run.tool_ledger.calls if c.tool_call_id == "tcbad")
    assert call.status is ToolCallStatus.ERROR
    assert run.status is RunStatus.COMPLETED  # 非法参数被拒后 run 继续


@pytest.mark.skipif(sys.platform != "win32" or (shutil.which("powershell") is None and shutil.which("pwsh") is None), reason="PowerShell DoD 需 Windows 真机")
async def test_dod_powershell_remove_item_asks_then_real_delete(tmp_path: Path) -> None:
    victim = tmp_path / "doomed.txt"
    victim.write_text("bye", encoding="utf-8")
    job = WindowsJobSandbox()
    runner = SandboxedProcessRunner(job, data_root=tmp_path)
    cmd = f"Remove-Item -Force {victim.as_posix()}"
    turns = [_write_turn("powershell", f'{{"command": "{cmd}", "timeout": 30}}'), _ANSWER]
    run = await _drive_with_decision(tmp_path, turns, "allow", sandbox=job, process_runner=runner)
    call = next(c for c in run.tool_ledger.calls if c.tool_call_id == "tc1")
    assert call.status is ToolCallStatus.SUCCESS
    assert not victim.exists()  # 真实进程删除成功（非 fake）
