"""RunController 接入 turn loop 的安全点消费语义（ADR-0013）。

B1/c3 追加：busy（非 idle）提交的用户输入必须成为 durable 事实（事实流出现 ``user_message``
且 seq 增加），终态 run 的迟到提交必须得明确错误（REJECTED_TERMINAL）而非静默丢失。
"""

from __future__ import annotations

from pathlib import Path

from questor.capabilities.tools.read import ReadTool
from questor.contracts.common import new_id
from questor.contracts.events import Cancel, EventType, SubmitMessage
from questor.contracts.inbox import InboxStatus
from questor.contracts.ports import StreamChunk
from questor.contracts.state_schema import Budget, CancelReason, ContentBlock, Message, Role, RunStatus
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.kernel.run_control import RunController
from questor.policy.react_policy import ReActPolicy
from questor.providers.fake import ScriptedProvider
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import Run

_ANSWER = [StreamChunk(kind="text", text="ok"), StreamChunk(kind="finish", finish_reason="stop")]


def _loop(tmp_path: Path) -> DefaultTurnLoop:
    read = ReadTool()
    return DefaultTurnLoop(
        provider=ScriptedProvider([_ANSWER]),
        policy=ReActPolicy(),
        permission=DefaultPermissionEngine(),
        bus=InProcessEventBus(None),
        tool_for=lambda name: read if name == "read" else None,
        tools=(read,),
        workspace_root=tmp_path,
    )


def _durable_loop(tmp_path: Path, store: SQLiteStore) -> tuple[DefaultTurnLoop, InProcessEventBus]:
    """带 store 的 loop：事实流可经 ``store.replay`` / bus 订阅回读（B1 的 durable 判据）。"""
    read = ReadTool()
    bus = InProcessEventBus(store)
    loop = DefaultTurnLoop(
        provider=ScriptedProvider([_ANSWER]),
        policy=ReActPolicy(),
        permission=DefaultPermissionEngine(),
        bus=bus,
        tool_for=lambda name: read if name == "read" else None,
        tools=(read,),
        store=store,
        workspace_root=tmp_path,
    )
    return loop, bus


def _run() -> Run:
    return Run(run_id=new_id("run"), budget=Budget(max_turns=3))


def _user_message(text: str) -> Message:
    return Message(id=new_id("msg"), role=Role.USER, content=(ContentBlock(type="text", text=text),), seq=0)


async def test_controller_prequeued_cancel_terminates_before_provider(tmp_path: Path) -> None:
    controller = RunController(_run())
    await controller.submit(Cancel(run_id=controller.run.run_id, reason=CancelReason.USER), source="test", idempotency_key="cancel")
    run = await _loop(tmp_path).drive_controller(controller)
    assert run.status is RunStatus.CANCELLED
    assert controller.closed is True


async def test_controller_prequeued_submit_runs_to_completion(tmp_path: Path) -> None:
    run = _run()
    controller = RunController(run)
    msg = _user_message("hi")
    await controller.submit(SubmitMessage(run_id=run.run_id, content=msg), source="test", idempotency_key="submit")
    final = await _loop(tmp_path).drive_controller(controller)
    assert final.status is RunStatus.COMPLETED
    assert msg.id in {m.id for m in final.context.items}
    assert controller.closed is True


async def test_submit_message_persists_when_busy(tmp_path: Path) -> None:
    """c3 验收：busy 下提交 → 事实流出现 USER_MESSAGE 且 seq 增加（旧实现无事件亦不 bump seq）。

    两条消息在同一安全点批量消费：第 1 条把 run 从 IDLE 拉起（run_started），第 2 条落在 RUNNING
    （busy）上——旧实现只把第 2 条追加进内存 context，事实流看不到、重连/重放也拉不到。
    """
    store = await SQLiteStore(str(tmp_path / "busy.db")).connect()
    try:
        loop, bus = _durable_loop(tmp_path, store)
        run = _run()
        controller = RunController(run)
        await controller.submit(SubmitMessage(run_id=run.run_id, content=_user_message("first")), source="test", idempotency_key="submit:1")
        await controller.submit(SubmitMessage(run_id=run.run_id, content=_user_message("second while busy")), source="test", idempotency_key="submit:2")
        final = await loop.drive_controller(controller)
        assert final.status is RunStatus.COMPLETED

        rows = await store.replay(final.run_id, 0)
        seqs = [row["seq"] for row in rows]
        assert seqs == sorted(set(seqs)), f"durable seq 不得重复：{seqs}"
        started = next(row for row in rows if row["type"] == "run_started")
        user_rows = [row for row in rows if row["type"] == "user_message"]
        assert [row["data"]["text"] for row in user_rows] == ["second while busy"], rows
        assert user_rows[0]["seq"] == started["seq"] + 1, "busy 提交必须占新的 durable seq"
        assert final.seq == max(seqs)

        # 重连/after_seq 重放：用户原话在对外投影里可见（EXTERNAL_EVENT_FIELDS 白名单），且终态收尾。
        replayed = [env async for env in bus.subscribe(final.run_id, 0)]
        user_env = next(env for env in replayed if env.type == EventType.USER_MESSAGE)
        assert user_env.data["text"] == "second while busy"
        assert set(user_env.data) == {"text", "truncated"}
        assert replayed[-1].type == EventType.RUN_COMPLETED
    finally:
        await store.close()


async def test_submit_after_terminal_is_rejected_and_surface_starts_a_new_run(tmp_path: Path) -> None:
    """终态 run 拒收：迟到 SubmitMessage → REJECTED_TERMINAL、事实流零新增（C13 不放宽）。

    surface 侧的唯一合法处置是**新建 run**（真实面均如此：cli.py:232 / http_sse.start_run 一条消息一个 run）。
    """
    store = await SQLiteStore(str(tmp_path / "late.db")).connect()
    try:
        loop, _ = _durable_loop(tmp_path, store)
        run = _run()
        controller = RunController(run)
        await controller.submit(SubmitMessage(run_id=run.run_id, content=_user_message("first")), source="test", idempotency_key="submit:1")
        final = await loop.drive_controller(controller)
        assert final.status is RunStatus.COMPLETED and controller.closed is True
        rows_before = await store.replay(final.run_id, 0)

        receipt = await controller.submit(
            SubmitMessage(run_id=run.run_id, content=_user_message("late input")),
            source="late",
            idempotency_key="submit:late",
        )
        assert receipt.status is InboxStatus.REJECTED_TERMINAL, receipt  # 明确错误，不静默丢
        assert await store.replay(final.run_id, 0) == rows_before, "迟到提交不得新增任何事实行"

        fresh = RunController(_run())
        receipt2 = await fresh.submit(
            SubmitMessage(run_id=fresh.run.run_id, content=_user_message("new run")),
            source="cli",
            idempotency_key=f"submit:{fresh.run.run_id}",
        )
        assert receipt2.status is InboxStatus.ACCEPTED  # 新建 run 是可用路径（本刀不改 surface）
    finally:
        await store.close()


async def test_terminal_controller_rejects_late_command(tmp_path: Path) -> None:
    run = _run()
    controller = RunController(run)
    msg = _user_message("hi")
    await controller.submit(SubmitMessage(run_id=run.run_id, content=msg), source="test", idempotency_key="submit")
    await _loop(tmp_path).drive_controller(controller)
    receipt = await controller.submit(
        Cancel(run_id=run.run_id, reason=CancelReason.USER),
        source="late",
        idempotency_key="late",
    )
    assert receipt.status is InboxStatus.REJECTED_TERMINAL
