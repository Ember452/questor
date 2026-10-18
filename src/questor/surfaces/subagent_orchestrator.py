"""L6 子 agent 编排实现：把 `SubagentSpawnerPort` 落到真 run（同进程 asyncio，ADR-0038）。

放 surfaces（L6）而非 capabilities（L3）：实体化子 run 需要 registry + bus + store + 组装子 loop
（`surface._loop`），这些都是传输/装配关注点；L3 的 `delegate` 工具只经端口调用本实现（C1：L3 不碰 L6）。
跨 run 一律经 Command（`registry.submit`）——父侧记账走 `SpawnSubagent`/`ReportChildTerminal`，
父下达取消走 `Cancel(owner)`；**绝无 `child.run.<field> =` 式直写**（C2/C16）。

委派协作语义（v1）：`delegate` 直接实体化并起跑子 run、再 await 其终态后返回（父等子结果）。子必须
由端口**直接起跑**（而非等父 loop 消费 SpawnSubagent），否则父阻塞在 await 上就不会 drain inbox → 死锁。
"""

from __future__ import annotations

import asyncio

from questor.contracts.events import (
    Cancel,
    ReportChildTerminal,
    SpawnSubagent,
    SubmitMessage,
    UpdateTaskTree,
)
from questor.contracts.state_schema import (
    Budget,
    CancelReason,
    ContentBlock,
    Message,
    Role,
    RunStatus,
    TaskKind,
    TaskNode,
)
from questor.contracts.subagent import SpawnRequest, SpawnResult
from questor.kernel.run_control import RunController
from questor.kernel.subagent_permission import project_parent_permission
from questor.state.domain_state import Run
from questor.surfaces.run_registry import RunRegistry

#: ADR-0041 D-5 推荐默认：父 budget 未显式设置时的 fan-out 宽度/深度上限。
_DEFAULT_MAX_PARALLEL = 4
_DEFAULT_MAX_TREE_DEPTH = 1
#: 子结果摘要进事件/回模型的上限（C18/ADR-0019：正文有界）。
_MAX_CHILD_SUMMARY_CHARS = 4096

_TERMINAL_MAP: dict[str, str] = {
    RunStatus.COMPLETED.value: "completed",
    RunStatus.FAILED.value: "failed",
    RunStatus.CANCELLED.value: "cancelled",
}


class SubagentOrchestrator:
    """实现 ``SubagentSpawnerPort``：spawn/委派子 run、子树冻结、跨 run 回报（registry 背书的 router）。"""

    def __init__(self, *, surface: object, bus: object, store: object, registry: RunRegistry) -> None:
        # surface=CliSurface（提供 _loop/_freeze_surface 组装子 loop）；bus=InProcessEventBus；store=StorePort。
        # 只持这些引用，在 delegate 时按需组装子 run——与 EventServer.start_run 同构。
        self._surface = surface
        self._bus = bus
        self._store = store
        self._registry = registry
        self._children: dict[str, set[str]] = {}  # parent_run_id -> live child_run_ids
        self._depth: dict[str, int] = {}  # run_id -> 编排树深度（顶层 run 不在表中，视作 0）
        self._pending: dict[str, asyncio.Future] = {}  # child_run_id -> delegate 等待的终态 future
        self._child_tasks: dict[str, asyncio.Task] = {}  # child_run_id -> 子驱动 asyncio 任务（供回收/测试 drain）

    async def delegate(self, request: SpawnRequest) -> SpawnResult:
        """fan-out gate → 父侧记账命令 → 直接起跑子 run → await 终态 → 回有界结果。"""
        parent = self._registry.get(request.parent_run_id)
        if parent is None:
            return SpawnResult(accepted=False, reason="unknown_parent")
        budget = parent.run.budget
        parent_depth = self._depth.get(request.parent_run_id, 0)
        max_depth = budget.max_tree_depth if budget.max_tree_depth is not None else _DEFAULT_MAX_TREE_DEPTH
        if parent_depth + 1 > max_depth:
            return SpawnResult(accepted=False, reason="depth_exceeded")
        live = self._children.setdefault(request.parent_run_id, set())
        max_parallel = budget.max_parallel_children if budget.max_parallel_children is not None else _DEFAULT_MAX_PARALLEL
        if len(live) >= max_parallel:
            return SpawnResult(accepted=False, reason="fanout_exceeded")

        child_run_id = _new_child_run_id()
        node_id = request.node_id or _new_child_run_id("node")
        # 父侧记账走 inbox（C2/C16）：先建 subagent 节点（UpdateTaskTree 经 reduce 的 DAG 校验），再 SpawnSubagent。
        node = TaskNode(id=node_id, title=request.objective[:256], objective=request.objective, kind=TaskKind.SUBAGENT)
        await self._registry.submit(
            request.parent_run_id,
            UpdateTaskTree(run_id=request.parent_run_id, upsert=(node,)),
            source="subagent",
            idempotency_key=f"plan:{request.parent_run_id}:{node_id}",
        )
        await self._registry.submit(
            request.parent_run_id,
            SpawnSubagent(run_id=request.parent_run_id, node_id=node_id, child_run_id=child_run_id, spawn_key=f"spawn:{node_id}"),
            source="subagent",
            idempotency_key=f"spawn:{request.parent_run_id}:{child_run_id}",
        )

        live.add(child_run_id)
        self._depth[child_run_id] = parent_depth + 1
        fut = asyncio.get_running_loop().create_future()
        self._pending[child_run_id] = fut
        # 直接起跑子 run（独立 asyncio 任务）；wait=True 父 await 其 future，False 则即刻返回（fire-and-forget）。
        self._child_tasks[child_run_id] = asyncio.create_task(
            self._drive_child(request.parent_run_id, node_id, child_run_id, request.objective, request.requested_mode)
        )
        if not request.wait:
            return SpawnResult(accepted=True, child_run_id=child_run_id)
        try:
            terminal, summary = await fut
        except asyncio.CancelledError:
            # 父被取消 → 委托取消：向子下达 Cancel(owner)，不硬杀；本 future 由 _drive_child 收尾清理。
            self._pending.pop(child_run_id, None)
            raise
        return SpawnResult(accepted=True, child_run_id=child_run_id, terminal_status=terminal, result=summary)

    async def materialize_child(self, parent_run_id: str, node_id: str, child_run_id: str) -> None:
        """幂等实体化（崩溃/回放重驱时补建子）；live 路径已在 delegate 起跑，这里通常 no-op。"""
        if self._registry.get(child_run_id) is not None:
            return  # 已在跑/已注册 → 不重复建（exactly-once：replay 不产生第二个子）
        parent = self._registry.get(parent_run_id)
        if parent is None:
            return
        node = next((n for n in parent.run.task_tree.nodes if n.id == node_id), None)
        objective = node.objective if node is not None else ""
        self._children.setdefault(parent_run_id, set()).add(child_run_id)
        self._depth.setdefault(child_run_id, self._depth.get(parent_run_id, 0) + 1)
        asyncio.create_task(self._drive_child(parent_run_id, node_id, child_run_id, objective, None))

    async def on_parent_terminal(self, parent_run_id: str) -> None:
        """父终态 → 冻结子树：向每个 live 子提 Cancel(owner)（C7，不硬杀）；无子 no-op。"""
        for child_run_id in tuple(self._children.get(parent_run_id, ())):
            await self._registry.submit(
                child_run_id,
                Cancel(run_id=child_run_id, reason=CancelReason.OWNER),
                source="subagent-parent",
                idempotency_key=f"cancel:{parent_run_id}:{child_run_id}",
            )

    async def _drive_child(self, parent_run_id: str, node_id: str, child_run_id: str, objective: str, requested_mode: str | None) -> None:
        """建子 Run（权限投影自父，⊆父 fail-closed）→ 注册 → SubmitMessage(objective) → 驱动到终态 → 回父。"""
        parent = self._registry.get(parent_run_id)
        try:
            if parent is None:
                self._complete_child(child_run_id, parent_run_id, node_id, "cancelled", "")
                return
            child_ctx = project_parent_permission(parent.run.permission_ctx, requested_mode=requested_mode)
            child = Run(run_id=child_run_id, budget=Budget(), permission_ctx=child_ctx)
            controller = RunController(child)
            self._registry.register(controller)
            msg = Message(id=_new_child_run_id("msg"), role=Role.USER, content=(ContentBlock(type="text", text=objective),), seq=0)
            await self._registry.submit(
                child_run_id,
                SubmitMessage(run_id=child_run_id, content=msg),
                source="subagent",
                idempotency_key=f"submit:{child_run_id}",
            )
            tool_surface = self._surface._freeze_surface(child_run_id, [])  # 复用装配：子用内置工具面（v1 不给子挂 MCP）
            loop = self._surface._loop(self._bus, asyncio.Event(), tool_surface, subagent_spawner=self)
            final = await loop.drive_controller(controller)
            terminal = _TERMINAL_MAP.get(final.status.value, "failed")
            await self._complete_child(child_run_id, parent_run_id, node_id, terminal, _last_assistant_text(final))
        except Exception as exc:  # noqa: BLE001 - 子编排故障绝不带崩父（C10）：归一为子 failed 并回父
            await self._complete_child(child_run_id, parent_run_id, node_id, "failed", f"child orchestration error: {type(exc).__name__}")

    async def _complete_child(self, child_run_id: str, parent_run_id: str, node_id: str, terminal: str, summary: str) -> None:
        """子终态收尾：先向父 inbox **await** 提 ``ReportChildTerminal``（bookkeeping + peer_ended），
        **再**解 waiter——保证父恢复时 report 已入队，peer_started→peer_ended 顺序确定。

        父若已终态则得 REJECTED_TERMINAL（不复活，诚实 at-least-once；子已在自己账本落终态）。"""
        self._children.get(parent_run_id, set()).discard(child_run_id)
        bounded = (summary or "")[:_MAX_CHILD_SUMMARY_CHARS]
        await self._registry.submit(
            parent_run_id,
            ReportChildTerminal(
                run_id=parent_run_id,
                child_run_id=child_run_id,
                node_id=node_id,
                terminal_status=terminal,
                resumable_hint=terminal == "cancelled",
            ),
            source="subagent",
            idempotency_key=f"report:{parent_run_id}:{child_run_id}",
        )
        fut = self._pending.pop(child_run_id, None)
        if fut is not None and not fut.done():
            fut.set_result((terminal, bounded))


def _new_child_run_id(prefix: str = "run") -> str:
    from questor.contracts.common import new_id

    return new_id(prefix)


def _last_assistant_text(run: Run) -> str:
    """取子 run 最后一条 assistant 可见文本作为回父摘要（有界、非原文全量）。"""
    for message in reversed(run.context.items):
        if message.role is Role.ASSISTANT:
            text = "".join(b.text or "" for b in message.content if b.type == "text")
            if text:
                return text
    return ""
