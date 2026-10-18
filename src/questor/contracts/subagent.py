"""L0 子 agent 编排契约：跨 run 端口 + spawn 请求/结果值对象（design/00 L3/L5；ADR-0038）。

放最内层 ``contracts``：kernel(L2) 与 capabilities(L3) 都只认这里的抽象，实现体经注入
落地（C1/C14）——kernel 绝不 import surfaces/capabilities 具体实现。**跨 run 一律经 Command**
（C2/C16）：这两个端口是"父下达子 / 子回父"的唯一合法通道，无任何跨 run 字段直写。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from questor.contracts.events import Command
from questor.contracts.inbox import InboxReceipt


@dataclass(frozen=True, slots=True)
class SpawnRequest:
    """策略/委派工具发起的一次 spawn 意图（尚未生成 child_run_id）。

    ``objective`` 是子任务的短标签（进子 run 的首条 user 消息），**不得含父全量 context**（C18）；
    ``requested_mode`` 若给定仍会被夹到 ≤ 父（永不放大，ADR-0040）；``extra_deny`` 只会扩大子 denylist。
    ``wait``：True=委派即阻塞等子终态（协作内联取回结果）；False=fire-and-forget（不起回，
    父继续跑）——只有 fire-and-forget 才能同时挂多个 live 子、令宽度门 `max_parallel_children` 真实可达。
    """

    parent_run_id: str
    node_id: str
    objective: str
    requested_mode: str | None = None
    extra_deny: tuple[str, ...] = ()
    wait: bool = True


@dataclass(frozen=True, slots=True)
class SpawnResult:
    """spawn 受理/完成结果。``accepted`` 表示 gate 通过且子 run 已发起；
    委派模式下端口会**等子 run 到终态**后返回，附带 ``terminal_status`` 与有界 ``result`` 摘要。

    ``reason`` 记录被拒原因（fanout_exceeded/depth_exceeded/unknown_parent/not_wired）。``result``
    是有界摘要（子 run 定稿文本截断），非无界载荷（C18/ADR-0019）。
    """

    accepted: bool
    child_run_id: str | None = None
    reason: str | None = None
    terminal_status: str | None = None  # completed | failed | cancelled（delegate 等到终态后填）
    result: str | None = None  # 有界摘要，非原文


@runtime_checkable
class CommandRouterPort(Protocol):
    """向**其它** active run 的 inbox 提交 Command（跨 run 下达的唯一合法通道）。

    实现落 L6 surfaces（持 ``RunRegistry``），由组合根注入 kernel；kernel 只持本抽象（C1/S7）。
    未知/终态 run 返回明确 receipt（不静默），承 ADR-0013 inbox 语义。
    """

    async def submit(
        self,
        run_id: str,
        command: Command,
        *,
        source: str,
        idempotency_key: str,
    ) -> InboxReceipt: ...


@runtime_checkable
class SubagentSpawnerPort(Protocol):
    """子 agent 编排端口：spawn 一个子 = 独立 Run（同进程 asyncio，ADR-0038）。

    委派模式（v1 协作语义）：``delegate`` **直接实体化并起跑子 run、再 await 其终态**后返回（父等子结果）；
    同时将 ``SpawnSubagent``/``ReportChildTerminal`` 经**父 inbox**（Command）递交父 reduce 做记账 + 发
    ``peer_started/peer_ended``（跨 run 不直写，C2/C16）。子由端口直接起跑（而非等父消费 SpawnSubagent），
    否则父阻塞在 await 上就不会 drain inbox →死锁。

    - ``materialize_child``：**幂等**（子已注册则 no-op）；供崩溃/回放重实体化与 bookkeeping 路径。
    - ``on_parent_terminal``：父到终态 → 冻结子树（向未终态子提 ``Cancel(owner)``，不硬杀，C7）；无子 no-op。
    实现落 L6 surfaces（持 registry/bus/store/surface 组装子 loop），由组合根注入 kernel。
    """

    async def delegate(self, request: SpawnRequest) -> SpawnResult: ...

    async def materialize_child(self, parent_run_id: str, node_id: str, child_run_id: str) -> None: ...

    async def on_parent_terminal(self, parent_run_id: str) -> None: ...
