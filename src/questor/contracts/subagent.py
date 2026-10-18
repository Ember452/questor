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
    """

    parent_run_id: str
    node_id: str
    objective: str
    requested_mode: str | None = None
    extra_deny: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SpawnResult:
    """端口受理结果。**受理成功仅代表 Command 已入父 inbox**，子 run 的实体化在父 loop 消费点
    （reduce 受理 SpawnSubagent 后）由 ``materialize_child`` 完成（承 WriteMemory 的"reduce 发事件、
    消费点做 IO"，ADR-0038/§4.1）。``reason`` 记录被拒原因（fanout_exceeded/depth_exceeded/...）。
    """

    accepted: bool
    child_run_id: str | None = None
    reason: str | None = None


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

    两步、顺序固定，消解"reduce 受理前不得建子"的 exactly-once 边界：
    - ``request``：跑 fan-out gate（宽度/深度，ADR-0041）+ 投影子权限（ADR-0040）+ 生成 ``child_run_id``
      + 向**父 inbox** 提 ``SpawnSubagent``；被拒则返回带 ``reason`` 的 ``SpawnResult``。
    - ``materialize_child``：**仅当父 loop 消费 SpawnSubagent 且 reduce 受理成功后**被调用，才建子 Run、
      注册 ``RunController`` 并把子 loop 作为 asyncio 任务起跑；子到终态经 ``CommandRouterPort`` 向父提
      ``ReportChildTerminal``。
    实现落 L3 ``capabilities/subagent``（持 loop 工厂/registry/bus/store/permission 投影器），由组合根注入。
    """

    async def request(self, request: SpawnRequest) -> SpawnResult: ...

    async def materialize_child(
        self,
        parent_run_id: str,
        node_id: str,
        child_run_id: str,
        objective: str,
    ) -> None: ...
