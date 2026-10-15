"""L6 RunRegistry —— surfaces 到 Kernel Command Inbox 的唯一桥（ADR-0013；HARD C16）。

surfaces 层不 import reduce/Store，只持 active run 的 RunController 并向其提交 Command。
run 未注册或已终态关闭时返回明确 receipt，绝不静默。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from questor.contracts.events import Command
from questor.contracts.inbox import InboxReceipt, InboxStatus
from questor.kernel.run_control import RunController


@dataclass
class _ActiveRun:
    """注册表中一条 active run 的句柄。"""

    controller: RunController
    task: object | None = None


@dataclass
class RunRegistry:
    """active run → RunController 的映射；所有外部 Command 经此投递。"""

    _runs: dict[str, _ActiveRun] = field(default_factory=dict)

    def register(self, controller: RunController) -> None:
        self._runs[controller.run.run_id] = _ActiveRun(controller=controller)

    def set_task(self, run_id: str, task: object) -> None:
        active = self._runs.get(run_id)
        if active is not None:
            active.task = task

    def get(self, run_id: str) -> RunController | None:
        active = self._runs.get(run_id)
        return active.controller if active else None

    def unregister(self, run_id: str) -> None:
        self._runs.pop(run_id, None)

    def active_run_ids(self) -> tuple[str, ...]:
        return tuple(self._runs)

    async def submit(
        self,
        run_id: str,
        command: Command,
        *,
        source: str,
        idempotency_key: str,
    ) -> InboxReceipt:
        """向对应 run 的 inbox 提交 Command；未知 run 返回 unknown_run。"""
        controller = self.get(run_id)
        if controller is None:
            return InboxReceipt(accepted=False, status=InboxStatus.UNKNOWN_RUN, reason=f"no active run {run_id}")
        return await controller.submit(command, source=source, idempotency_key=idempotency_key)


__all__ = ["RunRegistry"]
