"""L5 SandboxPort —— “none” 后端（design/03 §4；HARD C9/T4）。

一个空后端**什么都不隔离**，因此内核必须 fail-closed：exec/high 风险工具一律 deny，
绝不裸执行。真正的后端（seatbelt/bubblewrap/Windows job）自 P2 起。P0/P1 只给出探针
形状 + 诚实的 False。"""

from __future__ import annotations

from questor.contracts.ports import SandboxPort


class NullSandbox(SandboxPort):
    """无任何隔离能力的沙箱后端；用于演示 fail-closed。"""

    def fences_writes(self) -> bool:
        return False

    def fences_network(self) -> bool:
        return False

    def isolates_process_tree(self) -> bool:
        return False

    def wrap_argv(self, capability: str, argv: tuple[str, ...]) -> tuple[str, ...]:
        raise NotImplementedError("sandbox wrapping lands in P2")


__all__ = ["NullSandbox"]
