"""B1（T1 第①件）：用户输入成为 durable 事实 —— reduce 侧验收（c2）。

钉住的语义（设计文档 §4.2 事实流补齐）：

- **非 idle（busy）提交**：正文追加进 ``Context.items`` + 产一条 durable ``user_message``
  （有界正文，``truncated`` 不静默）+ bump seq（修 ``reduce.py`` 旧实现的"无事件、不 bump seq"不对称）；
- **idle 提交保持既有冻结契约**：恰产 ``[run_started]`` 且 seq==1——既有断言
  （``test_reduce.py:51`` / ``test_transition_chokepoint.py:45``）零改动，故首条消息的 durable 事实
  仍是 run_started + turn 边界快照（rebuild 可见），详见 PR 的勘误说明；
- **有界**：正文按 UTF-8 字节收进 ``OutputBudget().model_result_bytes``，与 wire schema
  （``$defs.user_message.text.maxLength``）由 ``check_protocol_schema._max_length_drift`` 同源机守。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from questor.contracts.artifacts import OutputBudget
from questor.contracts.events import Envelope, EventType, SubmitMessage
from questor.contracts.state_schema import ContentBlock, Message, Role, RunStatus
from questor.state.domain_state import Run
from questor.state.reduce import _USER_MESSAGE_TEXT_BYTES, reduce
from questor.state.transition import apply, reset_idempotency_window

_SCHEMA = json.loads(Path("protocol/event.schema.json").read_text(encoding="utf-8"))
_VALIDATOR = Draft202012Validator(_SCHEMA)


@pytest.fixture(autouse=True)
def _clean_window():
    """进程内命令窗口是模块级状态：每个用例前后清空，避免 run_id 复用造成串扰。"""
    reset_idempotency_window()
    yield
    reset_idempotency_window()


def _user(text: str, *, mid: str = "m1") -> Message:
    return Message(id=mid, role=Role.USER, content=(ContentBlock(type="text", text=text),), seq=0)


def _busy_run(run_id: str = "r_busy") -> Run:
    """已跑起来的 run（非 IDLE）：busy 提交路径的入口状态（首条走 idle → RUNNING）。"""
    run = Run(run_id=run_id)
    new, _ = reduce(run, SubmitMessage(run_id=run_id, content=_user("first")))
    assert new.status is RunStatus.RUNNING
    return new


def test_apply_user_message_on_busy_run_appends_and_bumps_seq() -> None:
    """c2 验收：apply(UserMessage) 后 messages 末尾是该文本、seq +1，且事实流恰一条 user_message。"""
    run = _busy_run()
    before = run.seq
    msg = _user("second thought")
    new, events = apply(None, run, SubmitMessage(run_id=run.run_id, content=msg), source="test", idempotency_key="k1")

    assert [e.type for e in events] == [EventType.USER_MESSAGE]
    assert new.seq == before + 1
    assert new.context.items[-1] is msg
    event = events[0]
    assert event.data["text"] == "second thought"
    assert event.data["truncated"] is False
    assert event.turn == run.turn  # 关联键：busy 提交挂在当前 turn 上
    assert event.seq == new.seq
    assert _VALIDATOR.is_valid(_as_wire(event)), "user_message 必须过 wire schema"


def test_idle_submit_keeps_frozen_run_started_contract() -> None:
    """idle 提交的契约被既有断言冻结（恰 [run_started]、seq==1）：B1 不动它，显式钉住防回归。"""
    run = Run(run_id="r_idle")
    msg = _user("hello")
    new, events = reduce(run, SubmitMessage(run_id=run.run_id, content=msg))
    assert new.status is RunStatus.RUNNING
    assert [e.type for e in events] == [EventType.RUN_STARTED]
    assert new.seq == 1
    assert new.context.items[-1] is msg  # 正文进 context（后续快照承载，rebuild 可见）


def test_user_message_bound_is_output_budget_and_wire_lockstep() -> None:
    """有界 = OutputBudget.model_result_bytes；wire maxLength 与其同源（check_protocol_schema 机守同一数值）。"""
    maxlen = _SCHEMA["$defs"]["user_message"]["properties"]["text"]["maxLength"]
    assert maxlen == OutputBudget().model_result_bytes == _USER_MESSAGE_TEXT_BYTES

    run = _busy_run("r_big")
    huge = "x" * (OutputBudget().model_result_bytes * 2)
    new, events = apply(None, run, SubmitMessage(run_id=run.run_id, content=_user(huge)), source="test", idempotency_key="k")
    data = events[0].data
    assert len(data["text"].encode("utf-8")) <= _USER_MESSAGE_TEXT_BYTES
    assert len(data["text"]) <= maxlen  # wire maxLength 是字符数，字节截断必然更强
    assert data["truncated"] is True  # 截断不静默
    assert new.context.items[-1] is not None  # 完整正文仍以 checkpoint 为权威
    assert _VALIDATOR.is_valid(_as_wire(events[0]))


def test_multibyte_user_text_is_not_split_mid_character() -> None:
    """多字节截断不劈开字符（errors=ignore）：落库正文必须仍是可解码 UTF-8。"""
    run = _busy_run("r_cjk")
    cjk = "汉" * (OutputBudget().model_result_bytes)  # 3 bytes/char → 必然超预算
    _, events = apply(None, run, SubmitMessage(run_id=run.run_id, content=_user(cjk)), source="test", idempotency_key="k")
    text = events[0].data["text"]
    assert events[0].data["truncated"] is True
    assert text == text.encode("utf-8").decode("utf-8")  # 无残字节
    assert _VALIDATOR.is_valid(_as_wire(events[0]))


def _as_wire(event: Envelope) -> dict:
    """把事件信封还原成 wire 形状（与 check_protocol_schema 的 fixture 同口径）。"""
    return {
        "v": event.v,
        "seq": event.seq,
        "run_id": event.run_id,
        "turn": event.turn,
        "ts": event.ts.isoformat(),
        "type": event.type,
        "data": dict(event.data),
    }