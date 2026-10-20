"""B0 咽喉回归：``apply`` 幂等 / ``durable_form`` 形态 / ``append`` epoch 栅栏。

这三条是 v3 §4.1 的验收面：
- 同 ``idempotency_key`` + 同 digest 二次应用 → 不重复产事件；同 key 异 digest → 拒（不覆盖）；
- live-only 不入库、终态可判、配预算时字符串叶子有界；
- 陈旧 epoch / 无身份的写者在有租约时被 ``StaleWriterError`` 拒绝，正确 holder+epoch 通过。
"""

from __future__ import annotations

import time

import pytest

from questor.contracts.artifacts import OutputBudget
from questor.contracts.events import AdvanceTurn, Envelope, EventType, SubmitMessage
from questor.contracts.state_schema import ContentBlock, Message, Role
from questor.providers.store_sqlite import SQLiteStore, StaleWriterError
from questor.state.domain_state import Run
from questor.state.persist_form import durable_form, is_terminal
from questor.state.transition import IdempotencyConflictError, apply, reset_idempotency_window


@pytest.fixture(autouse=True)
def _clean_window():
    """进程内命令窗口是模块级状态：每个用例前后清空，避免 run_id 复用造成串扰。"""
    reset_idempotency_window()
    yield
    reset_idempotency_window()


def _run(run_id: str = "r_apply") -> Run:
    return Run(run_id=run_id)


def _submit(run: Run) -> SubmitMessage:
    msg = Message(id="m1", role=Role.USER, seq=0, content=(ContentBlock(type="text", text="go"),))
    return SubmitMessage(run_id=run.run_id, content=msg)


def test_apply_same_key_same_digest_is_noop() -> None:
    run = _run()
    command = _submit(run)
    first, events = apply(None, run, command, source="test", idempotency_key="k1")
    assert [e.type for e in events] == [EventType.RUN_STARTED]
    assert first.seq == 1

    second, again = apply(None, first, command, source="test", idempotency_key="k1")
    assert again == ()  # 不重复产事件
    assert second == first


def test_apply_same_key_different_digest_is_rejected() -> None:
    run = _run()
    first, _ = apply(None, run, _submit(run), source="test", idempotency_key="k1")
    # 同一状态已消费过 k1：同 key 换命令 = 冲突，拒（不允许后者覆盖前者）
    with pytest.raises(IdempotencyConflictError):
        apply(None, first, AdvanceTurn(run_id=run.run_id, turn=1), source="test", idempotency_key="k1")


def test_apply_requires_idempotency_key() -> None:
    run = _run()
    with pytest.raises(ValueError, match="idempotency_key"):
        apply(None, run, _submit(run), source="test", idempotency_key="")


def test_durable_form_drops_live_only_and_keeps_terminal() -> None:
    live = Envelope(v=1, seq=1, run_id="r", type=EventType.TEXT_DELTA, data={"delta": "x"})
    terminal = Envelope(v=1, seq=2, run_id="r", type=EventType.RUN_COMPLETED, data={})
    assert durable_form(live) is None
    assert durable_form(terminal) is terminal
    assert is_terminal(terminal)
    assert not is_terminal(live)


def test_durable_form_budget_bounds_text_leaves() -> None:
    env = Envelope(v=1, seq=1, run_id="r", type=EventType.WARNING, data={"message": "x" * 200})
    bounded = durable_form(env, OutputBudget(model_result_bytes=16))
    assert bounded is not None
    assert bounded.data["message"] != env.data["message"]
    assert "truncated" in bounded.data["message"]


async def test_append_accepts_current_holder_and_rejects_stale_epoch(tmp_path) -> None:
    path = str(tmp_path / "fence.db")
    writer = await SQLiteStore(path).connect()
    try:
        assert await writer.acquire_lease("r_lease", "h1", 1, ttl_seconds=30.0)
        assert writer.writer_identity("r_lease") == ("h1", 1)
        # 不给 holder/epoch：回落到本实例记录的租约身份 → 通过
        await writer.append("r_lease", ({"type": "run_started", "data": {}},))
        # 显式身份匹配 → 通过
        await writer.append("r_lease", ({"type": "turn_started", "data": {}},), holder="h1", epoch=1)

        # 模拟租约过期被他人夺走：清过期行 → h2/epoch2 取得
        assert await writer.reclaim_expired_leases(time.time() + 3600) == 1
        assert await writer.acquire_lease("r_lease", "h2", 2, ttl_seconds=30.0)
        with pytest.raises(StaleWriterError):
            await writer.append("r_lease", ({"type": "turn_started", "data": {}},), holder="h1", epoch=1)
        await writer.append("r_lease", ({"type": "turn_started", "data": {}},), holder="h2", epoch=2)
    finally:
        await writer.close()


async def test_append_rejects_unfenced_writer_while_lease_is_held(tmp_path) -> None:
    path = str(tmp_path / "fence2.db")
    holder = await SQLiteStore(path).connect()
    stranger = await SQLiteStore(path).connect()
    try:
        assert await holder.acquire_lease("r_held", "ha", 1, ttl_seconds=30.0)
        with pytest.raises(StaleWriterError):
            await stranger.append("r_held", ({"type": "run_started", "data": {}},))
        # 没人持租约的 run（内存/测试/只读回放）保持既有行为
        await stranger.append("r_free", ({"type": "run_started", "data": {}},))
    finally:
        await holder.close()
        await stranger.close()
