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
from questor.contracts.events import Envelope, EventType, FinalizeRun, SubmitMessage
from questor.contracts.state_schema import ContentBlock, Message, Role, RunStatus
from questor.kernel.loop import _transition_key
from questor.state.domain_state import Run
from questor.state.persist_form import SCAFFOLDING_CLOSE, SCAFFOLDING_OPEN, durable_form, strip_scaffolding
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


# --------------------------------------------------------------------------- #
# c3：内核幂等提交（内容派生键 / 终态拒收），覆盖 idle 与 busy
# --------------------------------------------------------------------------- #
def test_submit_key_is_content_derived() -> None:
    """幂等键 = ``submit:<turn>:<content_sha256>``：同内容同 state → 同键（可去重）；异内容 → 异键（不互撞）。

    旧通用键（type+游标）让同一安全点批量消费的两条不同消息撞成同键 → apply 抛
    ``IdempotencyConflictError``；内容派生键是 busy 批量提交正确性的前提。
    """
    run = _busy_run("r_key")
    key_a = _transition_key(SubmitMessage(run_id=run.run_id, content=_user("go", mid="a")), run)
    key_b = _transition_key(SubmitMessage(run_id=run.run_id, content=_user("go", mid="b")), run)
    key_c = _transition_key(SubmitMessage(run_id=run.run_id, content=_user("stop", mid="c")), run)
    assert key_a == key_b  # 同正文同 turn：同一意图（不同 Message id 不参与关键性）
    assert key_a != key_c  # 异正文：不同键，绝不互撞
    assert key_a.startswith(f"submit:{run.turn}:")
    assert len(key_a.rsplit(":", 1)[1]) == 64  # sha256 十六进制


def test_terminal_run_rejects_submit_with_warning_and_never_appends() -> None:
    """C13 不因 B1 放宽：终态后的 SubmitMessage 被拒（warning + bump seq），状态与 context 零变化。

    终态 run 无法在不放宽 C13 的前提下写入 → surface 的唯一合法处置是**新建 run**
    （CLI/http/openai 面本就“一条消息一个 run”）。
    """
    run = _busy_run("r_term")
    done, _ = reduce(run, FinalizeRun(run_id=run.run_id, status="completed", exit_reason="answered"))
    assert done.status is RunStatus.COMPLETED
    before_items = done.context.items
    new, events = apply(
        None,
        done,
        SubmitMessage(run_id=done.run_id, content=_user("late input", mid="late")),
        source="test",
        idempotency_key="k_late",
    )
    assert [e.type for e in events] == [EventType.WARNING]
    assert "already" in events[0].data["message"]
    assert new.status is RunStatus.COMPLETED
    assert new.context.items == before_items  # 绝不追加
    assert new.seq == done.seq + 1  # 警告仍占一个 durable seq（C2）
    assert _VALIDATOR.is_valid(_as_wire(events[0]))


# --------------------------------------------------------------------------- #
# c4：落库前剥注入脚手架（带内标记）——只剥内容，不做第二套去重
# --------------------------------------------------------------------------- #
def _user_message_env(text: str) -> Envelope:
    return Envelope(v=1, seq=7, run_id="r_strip", type=EventType.USER_MESSAGE, turn=1, data={"text": text, "truncated": False})


def test_marked_scaffolding_is_stripped_before_persisting() -> None:
    """c4 验收：带标记输入 → 持久正文不含标记（只留用户原话）；context（模型输入）不受影响。

    注入段是模型的合法输入（context 不动），但不是事实流里的「用户原话」——
    故只在 durable_form（落库唯一形态判定点）剥。
    """
    marked = f"real user words {SCAFFOLDING_OPEN}system injected preamble{SCAFFOLDING_CLOSE} and a closing line"
    env = _user_message_env(marked)
    durable = durable_form(env)
    assert durable is not None
    assert durable.data["text"] == "real user words  and a closing line"
    assert SCAFFOLDING_OPEN not in durable.data["text"] and SCAFFOLDING_CLOSE not in durable.data["text"]
    # 原信封（= context 侧消息的投影）与非 user_message 事件一律不动。
    assert env.data["text"] == marked
    assert durable_form(_user_message_env("plain words")).data["text"] == "plain words"
    assert _VALIDATOR.is_valid(_as_wire(durable))


def test_strip_scaffolding_shapes() -> None:
    """多段 / 未闭合（fail-closed 截到文末）/ 孤儿 CLOSE（只剥记号）/ 无标记（逐字节等价）。"""
    assert strip_scaffolding("a") == "a"
    assert strip_scaffolding("") == ""
    pair = f"x{SCAFFOLDING_OPEN}inj{SCAFFOLDING_CLOSE}y{SCAFFOLDING_OPEN}inj2{SCAFFOLDING_CLOSE}z"
    assert strip_scaffolding(pair) == "xyz"
    # 未闭合：边界未知，注入段其后全部剔除（绝不把注入文本当用户原话）。
    assert strip_scaffolding(f"keep{SCAFFOLDING_OPEN}inj keeps going") == "keep"
    # 孤儿 CLOSE：只剥记号本身，两侧文本保留。
    assert strip_scaffolding(f"left{SCAFFOLDING_CLOSE}right") == "leftright"


def test_same_content_repeated_apply_does_not_append_twice() -> None:
    """c4 验收：同内容重复 apply → 不重复追加；去重只靠 apply 幂等键，不靠标记扫描。"""
    run = _busy_run("r_dup")
    msg = _user("same words", mid="dup")
    command = SubmitMessage(run_id=run.run_id, content=msg)
    key = _transition_key(command, run)

    first, events = apply(None, run, command, source="test", idempotency_key=key)
    assert [e.type for e in events] == [EventType.USER_MESSAGE]

    second, again = apply(None, first, command, source="test", idempotency_key=key)
    assert again == ()  # 幂等 no-op：不重复产事件
    assert second == first  # 也不重复追加 context
    assert sum(1 for m in second.context.items if m is msg) == 1

    # 不同内容（同 state 游标不同也会不同键）→ 各自落一条，不互相误判。
    other = SubmitMessage(run_id=first.run_id, content=_user("different words", mid="dup2"))
    third, events3 = apply(None, first, other, source="test", idempotency_key=_transition_key(other, first))
    assert [e.type for e in events3] == [EventType.USER_MESSAGE]
    assert third.context.items[-1].content[0].text == "different words"