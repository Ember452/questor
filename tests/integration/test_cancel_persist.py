"""P1 fix #2 guard — Cancel with an open tool must persist without seq collision."""

from __future__ import annotations

from questor.contracts.common import new_id
from questor.contracts.events import AppendAssistantMessage, Cancel, SubmitMessage
from questor.contracts.state_schema import CancelReason, ContentBlock, Message, Role, RunStatus
from questor.kernel.events import InProcessEventBus
from questor.providers.store_sqlite import SQLiteStore
from questor.state.domain_state import Run
from questor.state.reduce import reduce


def _user(text: str) -> Message:
    return Message(id=new_id("msg"), role=Role.USER, content=(ContentBlock(type="text", text=text),), seq=0)


def _assistant_tool(call_id: str) -> Message:
    return Message(
        id=new_id("msg"),
        role=Role.ASSISTANT,
        content=(ContentBlock(type="tool_use", tool_use_id=call_id, name="read", input={"file_path": "a"}),),
        seq=1,
    )


async def test_cancel_with_open_tool_persists_cleanly() -> None:
    store = await SQLiteStore(":memory:").connect()
    bus = InProcessEventBus(store)
    run = Run(run_id=new_id("run"))

    run, events = reduce(run, SubmitMessage(run_id=run.run_id, content=_user("hi")))
    run, more = reduce(run, AppendAssistantMessage(run_id=run.run_id, turn=1, message=_assistant_tool("tc_1")))
    run, cancel_events = reduce(run, Cancel(run_id=run.run_id, reason=CancelReason.USER))

    for env in (*events, *more, *cancel_events):
        await bus.emit(env)  # pre-fix: two events share a seq -> IntegrityError here

    assert run.status is RunStatus.CANCELLED
    assert await store.sequence_head(run.run_id) == run.seq
    replayed = await store.replay(run.run_id, 0)
    seqs = [e["seq"] for e in replayed]
    assert seqs == sorted(set(seqs))  # no dup on disk
    terminals = [e for e in replayed if e["type"] in {"run_cancelled", "run_completed", "run_failed"}]
    assert len(terminals) == 1
    await store.close()
