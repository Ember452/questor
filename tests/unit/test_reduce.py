"""P1 T3 DoD — ``reduce`` invariants: single writer, pairing, cancel backfill, terminal freeze."""

from __future__ import annotations

import pytest

from questor.contracts.common import new_id
from questor.contracts.events import (
    AppendAssistantMessage,
    Cancel,
    FinalizeRun,
    RecordToolResult,
    SubmitMessage,
)
from questor.contracts.state_schema import (
    CancelReason,
    ContentBlock,
    Message,
    Role,
    RunStatus,
    ToolCallStatus,
)
from questor.state.domain_state import Run
from questor.state.reduce import reduce


def _run() -> Run:
    return Run(run_id=new_id("run"))


def _user(text: str) -> Message:
    return Message(id=new_id("msg"), role=Role.USER, content=(ContentBlock(type="text", text=text),), seq=0)


def _assistant_toolcall(call_id: str) -> Message:
    return Message(
        id=new_id("msg"),
        role=Role.ASSISTANT,
        content=(ContentBlock(type="tool_use", tool_use_id=call_id, name="read", input={"file_path": "a"}),),
        seq=1,
    )


def test_submit_starts_run() -> None:
    run = _run()
    new, events = reduce(run, SubmitMessage(run_id=run.run_id, content=_user("hi")))
    assert new.status is RunStatus.RUNNING
    assert len(new.context.items) == 1
    assert [e.type for e in events] == ["run_started"]


def test_append_tool_use_registers_pending_call() -> None:
    run, _ = reduce(_run(), SubmitMessage(run_id="run_a", content=_user("hi")))
    call_id = "tc_1"
    new, events = reduce(run, AppendAssistantMessage(run_id=run.run_id, turn=1, message=_assistant_toolcall(call_id)))
    assert new.tool_ledger.calls[0].status is ToolCallStatus.PENDING
    assert events[-1].type == "message_completed"


def test_record_result_closes_pairing() -> None:
    run, _ = reduce(_run(), SubmitMessage(run_id="run_b", content=_user("hi")))
    run, _ = reduce(run, AppendAssistantMessage(run_id=run.run_id, turn=1, message=_assistant_toolcall("tc_1")))
    new, events = reduce(run, RecordToolResult(run_id=run.run_id, tool_call_id="tc_1", status="success", result="ok"))
    assert new.tool_ledger.calls[0].status is ToolCallStatus.SUCCESS
    assert events[-1].type == "tool_completed"
    assert any(b.type == "tool_result" for m in new.context.items for b in m.content)


def test_duplicate_tool_use_rejected() -> None:
    run, _ = reduce(_run(), SubmitMessage(run_id="run_c", content=_user("hi")))
    run, _ = reduce(run, AppendAssistantMessage(run_id=run.run_id, turn=1, message=_assistant_toolcall("tc_1")))
    new, events = reduce(run, AppendAssistantMessage(run_id=run.run_id, turn=2, message=_assistant_toolcall("tc_1")))
    assert new.tool_ledger.calls == run.tool_ledger.calls  # unchanged
    assert events[-1].type == "warning"


def test_cancel_backfills_open_calls_and_one_terminal() -> None:
    run, _ = reduce(_run(), SubmitMessage(run_id="run_d", content=_user("hi")))
    run, _ = reduce(run, AppendAssistantMessage(run_id=run.run_id, turn=1, message=_assistant_toolcall("tc_1")))
    new, events = reduce(run, Cancel(run_id=run.run_id, reason=CancelReason.USER))
    assert new.status is RunStatus.CANCELLED
    assert new.tool_ledger.calls[0].status is ToolCallStatus.ERROR  # backfilled
    terminals = [e for e in events if e.type in {"run_cancelled", "run_completed", "run_failed"}]
    assert len(terminals) == 1
    # seqs must be unique + strictly increasing, and Run.seq == the last one
    # (guards the #2 collision: backfill event vs terminal sharing a seq).
    seqs = [e.seq for e in events]
    assert seqs == sorted(set(seqs)) and len(seqs) >= 2
    assert new.seq == max(seqs)


def test_terminal_run_freezes_later_commands() -> None:
    run, _ = reduce(_run(), SubmitMessage(run_id="run_e", content=_user("hi")))
    run, _ = reduce(run, FinalizeRun(run_id=run.run_id, status="completed"))
    new, events = reduce(run, SubmitMessage(run_id=run.run_id, content=_user("more")))
    assert new == run  # frozen
    assert events[-1].type == "warning"


def test_reduce_is_cow_old_state_unchanged() -> None:
    run = _run()
    snapshot_calls = run.tool_ledger.calls
    _, _ = reduce(run, SubmitMessage(run_id=run.run_id, content=_user("hi")))
    assert run.tool_ledger.calls == snapshot_calls
    assert run.status is RunStatus.IDLE  # original not mutated


def test_leaf_dict_is_immutable() -> None:
    # C2: frozen dataclass with a dict leaf was the #1 false-immutability gap.
    from questor.contracts.state_schema import ToolCall

    call = ToolCall(tool_call_id="tc_1", turn=1, name="read", args={"file_path": "a"})
    with pytest.raises(TypeError):
        call.args["file_path"] = "ESCAPED"  # type: ignore[index]


def test_cow_states_do_not_share_mutable_leaf() -> None:
    run, _ = reduce(_run(), SubmitMessage(run_id="run_x", content=_user("hi")))
    run, _ = reduce(run, AppendAssistantMessage(run_id=run.run_id, turn=1, message=_assistant_toolcall("tc_1")))
    new, _ = reduce(run, RecordToolResult(run_id=run.run_id, tool_call_id="tc_1", status="success", result="ok"))
    # mutating any leaf across either state must raise -> no cross-state leak
    for state in (run, new):
        with pytest.raises(TypeError):
            state.tool_ledger.calls[0].args["x"] = "y"  # type: ignore[index]
