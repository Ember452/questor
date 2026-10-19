"""压缩摘要必须回灌给模型（track5-backbone MAJ-4）。

逐出的中段既不在 ``context.items``、若 ``Context.summary`` 不注入 provider 请求，模型就直接丢内容——
"可恢复压缩不丢上下文"名不副实。这里用 spy provider 捕获实际请求，证伪：设了 summary 后，
发往 provider 的 messages 里必须带上摘要文本。"""

from __future__ import annotations

from pathlib import Path

from questor.contracts.common import new_id
from questor.contracts.ports import StreamChunk
from questor.contracts.state_schema import Budget
from questor.kernel.events import InProcessEventBus
from questor.kernel.loop import DefaultTurnLoop
from questor.kernel.permissions import DefaultPermissionEngine
from questor.policy.react_policy import ReActPolicy
from questor.state.domain_state import Context, Run

_ANSWER = [StreamChunk(kind="text", text="ok"), StreamChunk(kind="finish", finish_reason="stop")]


class _SpyProvider:
    def __init__(self) -> None:
        self.requests: list = []

    async def stream(self, request):
        self.requests.append(request)
        for chunk in _ANSWER:
            yield chunk


def _texts(messages) -> str:
    return "\n".join(block.text or "" for m in messages for block in m.content)


async def test_compaction_summary_reaches_provider_request(tmp_path: Path) -> None:
    spy = _SpyProvider()
    loop = DefaultTurnLoop(
        provider=spy,  # type: ignore[arg-type]
        policy=ReActPolicy(),
        permission=DefaultPermissionEngine(),
        bus=InProcessEventBus(None),
        tool_for=lambda name: None,
        tools=(),
        workspace_root=tmp_path,
        model="m",
    )
    summary = "EARLIER-SUMMARY-FACT"
    run = Run(run_id=new_id("run"), budget=Budget(max_turns=2), context=Context(items=(), summary=summary))
    await loop.drive(run, "继续")

    assert spy.requests, "provider 未被调用"
    first_msgs = spy.requests[0].messages
    assert summary in _texts(first_msgs), f"压缩摘要未注入 provider 请求（MAJ-4）：{first_msgs!r}"
