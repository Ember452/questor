"""L2 resume-and-drive：从持久态重建 Run 并交回唯一 turn 循环续跑到终态（ADR-0021）。

编排归 Kernel（surfaces 零业务，C14/C16）：本模块只做"重建 + 挂 RunController + 交回唯一 loop"，
不自行 ``reduce``。未闭合 ``tool_use`` 的补齐/re-dispatch 由 ``DefaultTurnLoop`` 在 ``_drive_controller``
入口的 ``_resume_settle_open_calls`` 完成——保证进入 provider 前配对完整（不半 tool_use 喂回 provider）。

surfaces（CLI ``--resume`` / HTTP ``POST /runs/{id}/resume``）注入装配好的 ``turn_loop`` + ``store`` 调本函数；
``turn_loop`` 以鸭子类型接收（不 import ``loop``，避免 kernel 内环依赖）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from questor.kernel.recovery import rebuild_run
from questor.kernel.run_control import RunController

if TYPE_CHECKING:
    from questor.contracts.ports import StorePort
    from questor.state.domain_state import Run


async def resume_and_drive(turn_loop: object, store: StorePort, run_id: str, *, controller: RunController | None = None, now=None) -> Run | None:
    """重建 ``run_id`` 的权威状态并续跑到唯一终态；无快照（未知 run）返回 ``None``。

    幂等：``rebuild_run`` 对已终态 run 也返回其终态快照，``drive_controller`` 遇终态 run 直接
    ``_resume_settle_open_calls`` 空转后返回，不重复执行已完成的工具（派发侧判 OPEN 状态）。

    ``controller``：surfaces 若要把续跑中的 run 注册回 Command Inbox（使后续 HTTP 审批/取消能路由），
    可先传入已注册的 RunController；否则本函数自内部用重建的 run 新建一个（C16：仍经 RunController，不直 reduce）。
    """
    if controller is not None:
        return await turn_loop.drive_controller(controller)  # type: ignore[attr-defined]
    run = await rebuild_run(store, run_id, now=now)
    if run is None:
        return None
    return await turn_loop.drive_controller(RunController(run))  # type: ignore[attr-defined]


__all__ = ["resume_and_drive"]
