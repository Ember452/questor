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
from questor.kernel.durability import resume_and_drive
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.kernel.recovery import rebuild_run
from questor.kernel.run_control import RunController
from questor.policy.react_policy import ReActPolicy
from questor.providers.fake import ScriptedProvider
from questor.providers.litellm_adapter import to_openai_messages
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import Run
from questor.state.persist_form import SCAFFOLDING_CLOSE, SCAFFOLDING_OPEN

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


async def test_resume_transcript_equals_production_transcript(tmp_path: Path) -> None:
    """c5（本刀核验测试）：一次 run 提交 3 条消息 → ``rebuild_run`` + ``to_openai_messages``
    重建请求与生产路径**逐条相等**；kill（关库、新连接模拟新进程）后经 ``--resume`` 入口
    重建，可见转录不丢、也不被续跑改写。

    3 条消息在同一安全点批量消费：第 1 条 idle（run_started），第 2/3 条 busy（各产 user_message）。
    第 3 条带注入标记 → 两种形态各归其位：持久事实（user_message.text）无标记，
    模型输入（context → 重建请求）保留注入段。
    """
    db = str(tmp_path / "replay.db")
    store = await SQLiteStore(db).connect()
    loop, _bus = _durable_loop(tmp_path, store)
    run = _run()
    controller = RunController(run)
    texts = ["first", "second while busy", f"third {SCAFFOLDING_OPEN}injected segment{SCAFFOLDING_CLOSE} tail"]
    for index, text in enumerate(texts, start=1):
        await controller.submit(
            SubmitMessage(run_id=run.run_id, content=_user_message(text)),
            source="test",
            idempotency_key=f"submit:{index}",
        )
    production = await loop.drive_controller(controller)
    assert production.status is RunStatus.COMPLETED
    production_messages = to_openai_messages(production.context.items, None)
    assert [m["content"] for m in production_messages if m["role"] == "user"] == texts

    rows = await store.replay(production.run_id, 0)
    user_rows = [row for row in rows if row["type"] == "user_message"]
    assert [row["data"]["text"] for row in user_rows] == ["second while busy", "third  tail"], user_rows
    assert all(SCAFFOLDING_OPEN not in row["data"]["text"] for row in user_rows), user_rows

    await store.close()  # kill：丢弃进程内一切，只剩磁盘
    reopened = await SQLiteStore(db).connect()  # 新连接 = 新进程语义
    try:
        rebuilt = await rebuild_run(reopened, production.run_id)
        assert rebuilt is not None
        assert to_openai_messages(rebuilt.context.items, None) == production_messages  # 重放=生产（逐条相等）
        assert [m["content"] for m in to_openai_messages(rebuilt.context.items, None) if m["role"] == "user"] == texts

        resumed = await resume_and_drive(_durable_loop(tmp_path, reopened)[0], reopened, production.run_id)
        assert resumed is not None and resumed.status is RunStatus.COMPLETED  # 终态续跑幂等空转
        assert to_openai_messages(resumed.context.items, None) == production_messages  # 续跑不改写转录
        assert await reopened.replay(production.run_id, 0) == rows  # 也不新增事实行
    finally:
        await reopened.close()


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
