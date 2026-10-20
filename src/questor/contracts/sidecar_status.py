"""L0 sidecar 生命周期状态契约（§6-5；HARD C14/C15）。

**独立 status 面**：这是**进程级**状态，不属于任何 run，故**不进** per-run 事件信封
（``contracts/events.py`` 的 ``Envelope`` 要求 ``run_id``）；单列一套 wire 契约 + schema，
由**宿主壳**（当前 = Tauri Rust 侧的崩溃探测）生产、UI 消费。消费者遇未知 ``state`` 应按
``crashed`` 保守处理（生命周期状态是错误类信号，不静默丢弃）。

壳中立（OPT-10）：本契约只固定数据形状与 bootstrap ``{host,port,generation,pid,token}``，
**不假定具体壳**；换成 Electron/IDE 壳时只换生产者实现与守卫参数（``check_desktop_csp.py`` /
``check_thin_client.py`` 的目标路径与符号），wire 形状与三个不变量不变。

字段 ``detail`` 有界、**永不**含原始崩溃栈/机密（C20：wire 非载荷第二载体），仅短归因。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

#: sidecar 生命周期状态取值域（wire snake_case）。只增不改。
SIDECAR_LIFECYCLE_STATES: frozenset[str] = frozenset({"starting", "ready", "stopping", "stopped", "crashed"})

#: ``sidecar_status`` wire 载荷字段白名单（与 ``protocol/sidecar_status.schema.json`` 属性集 lockstep）。
SIDECAR_STATUS_FIELDS: frozenset[str] = frozenset({"state", "generation", "detail"})

#: ``detail`` 上界：足够写短归因，绝不装崩溃栈/原文。
_MAX_DETAIL_LEN = 256


@dataclass(frozen=True, slots=True)
class SidecarStatus:
    """sidecar 进程级状态快照。``generation`` 对应壳的 ``Fence`` 代次（崩溃重启后自增）。"""

    state: str
    generation: int
    detail: str | None = None
    type: ClassVar[str] = "sidecar_status"

    def __post_init__(self) -> None:
        if self.state not in SIDECAR_LIFECYCLE_STATES:
            raise ValueError(f"unknown sidecar state: {self.state!r}")
        if self.generation < 0:
            raise ValueError("SidecarStatus.generation must be >= 0")
        if self.detail is not None and len(self.detail) > _MAX_DETAIL_LEN:
            raise ValueError(f"SidecarStatus.detail exceeds {_MAX_DETAIL_LEN} chars")


__all__ = [
    "SIDECAR_LIFECYCLE_STATES",
    "SIDECAR_STATUS_FIELDS",
    "SidecarStatus",
]
