"""L2 capability floor（ADR-0015；HARD C9/C17）。

这是权限求值前、但敏感路径之后的“不可被 mode 覆盖”能力下限。输入只有能力事实与 sandbox
descriptor；函数不执行工具，也不读配置。
"""

from __future__ import annotations

from questor.contracts.permission import PermissionDecision, PermissionOutcome
from questor.contracts.sandbox import SandboxBackend, SandboxDescriptor
from questor.contracts.shell_analysis import ShellAnalysis
from questor.contracts.tool import Capability, ToolSpec


def apply_capability_floor(
    *,
    tool_spec: ToolSpec,
    sandbox: SandboxDescriptor,
    shell_analysis: ShellAnalysis | None,
    args_summary: str,
    mode: str,
) -> PermissionOutcome | None:
    """返回 floor 决策；``None`` 表示 sandbox 足够，交给普通 rules/mode。

    `mode` 只作为理由文案输入；这里绝不读取它来放宽下限。调用方之后仍会处理 rules/mode。
    """
    capability = tool_spec.capability

    if capability is Capability.NETWORK and not sandbox.fences_network:
        return PermissionOutcome(
            decision=PermissionDecision.DENY,
            reason=f"network capability denied fail-closed: no sandbox network fence ({sandbox.backend.value}, mode={mode})",
            args_summary=args_summary,
            warnings=(sandbox.limitation,),
            floor_applied="network-capability",
        )

    if capability is Capability.EXEC:
        if sandbox.backend is SandboxBackend.NONE:
            return PermissionOutcome(
                decision=PermissionDecision.DENY,
                reason=f"exec capability denied fail-closed: no sandbox backend available (mode={mode} cannot bypass this floor)",
                args_summary=args_summary,
                warnings=(sandbox.limitation,),
                floor_applied="exec-capability",
            )
        # 能力事实驱动，而非后端名：一个名为 seatbelt/bwrap 却未真正围栏写(fences_writes)的 descriptor
        # 必须加严，不因后端标签“看起来是强隔离”就静默放行（#154/MAJ-1：扩展新沙箱后端时的 fail-open 陷阱）。
        if not sandbox.fences_writes:
            proven_read_only = shell_analysis is not None and shell_analysis.all_read_only and not shell_analysis.write_paths
            if not proven_read_only:
                return PermissionOutcome(
                    decision=PermissionDecision.ASK,
                    reason=(
                        f"exec capability floor: backend {sandbox.backend.value} has no filesystem write fence; "
                        f"manual approval is required even in {mode}"
                    ),
                    args_summary=args_summary,
                    warnings=(sandbox.limitation, "manual approval is not OS write isolation"),
                    floor_applied="exec-capability",
                )
        return None

    if capability is Capability.WRITE and not sandbox.fences_writes:
        return PermissionOutcome(
            decision=PermissionDecision.ASK,
            reason=(
                f"write capability floor: backend {sandbox.backend.value} has no filesystem write fence; "
                f"manual approval plus tool containment is required even in {mode}"
            ),
            args_summary=args_summary,
            warnings=(sandbox.limitation, "manual approval is not OS write isolation"),
            floor_applied="write-capability",
        )

    return None


__all__ = ["apply_capability_floor"]
