"""P9 T6c：OpenAI 投影适配器纯映射（envelope→chunk；design/02 §9 X5/§10 映射表）。

投影适配器不是第二写者/第二真相——本测只钉映射：``text_delta``→``delta.content``、
``tool_started``→``tool_calls``、终态→``finish_reason``+``[DONE]``、``run_failed``→错误编进末帧。
"""

from __future__ import annotations

import asyncio

from questor.contracts.events import Envelope, EventType
from questor.surfaces.openai_compat import project_openai_stream


def _env(etype: str, data: dict) -> Envelope:
    return Envelope(v=1, seq=1, run_id="r1", type=etype, turn=0, data=data)


async def _drain(envelopes: list[Envelope]) -> list[object]:
    async def _aiter():
        for env in envelopes:
            yield env

    out = []
    async for frame in project_openai_stream(_aiter(), completion_id="chatcmpl-1", model="questor", created=1700000000):
        out.append(frame)
    return out


def test_text_delta_streams_content_then_done() -> None:
    frames = asyncio.run(_drain([
        _env(EventType.RUN_STARTED, {"run_id": "r1"}),
        _env(EventType.TEXT_DELTA, {"delta": "he"}),
        _env(EventType.TEXT_DELTA, {"delta": "llo"}),
        _env(EventType.RUN_COMPLETED, {"usage": {}}),
    ]))
    datas = [f for f in frames if f != "[DONE]"]
    # 首帧 role delta、两条 content、末帧 finish_reason stop，末尾 [DONE]。
    assert datas[0]["choices"][0]["delta"].get("role") == "assistant"
    contents = [d["choices"][0]["delta"].get("content") for d in datas if d["choices"][0]["delta"].get("content")]
    assert contents == ["he", "llo"]
    assert datas[-1]["choices"][0]["finish_reason"] == "stop"
    assert frames[-1] == "[DONE]"


def test_tool_started_maps_to_tool_calls_delta() -> None:
    frames = asyncio.run(_drain([
        _env(EventType.RUN_STARTED, {"run_id": "r1"}),
        _env(EventType.TOOL_STARTED, {"tool_call_id": "tc1", "name": "read", "capability": "readonly", "risk": "low", "args_summary": "a"}),
        _env(EventType.RUN_COMPLETED, {"usage": {}}),
    ]))
    tool_frames = [f for f in frames if f != "[DONE]" and isinstance(f, dict) and f["choices"][0]["delta"].get("tool_calls")]
    assert tool_frames
    tc = tool_frames[0]["choices"][0]["delta"]["tool_calls"][0]
    assert tc["id"] == "tc1" and tc["function"]["name"] == "read"


def test_run_failed_encodes_error_in_terminal_frame_and_done() -> None:
    frames = asyncio.run(_drain([
        _env(EventType.RUN_STARTED, {"run_id": "r1"}),
        _env(EventType.RUN_FAILED, {"error": {"code": "timeout", "message": "boom", "retryable": False}}),
    ]))
    assert frames[-1] == "[DONE]"
    err_frame = next(f for f in frames if f != "[DONE]" and isinstance(f, dict) and f.get("x_questor", {}).get("error"))
    assert err_frame["x_questor"]["error"]["code"] == "timeout"
    assert err_frame["choices"][0]["finish_reason"] == "stop"


def test_run_cancelled_finishes_cleanly() -> None:
    frames = asyncio.run(_drain([
        _env(EventType.RUN_STARTED, {"run_id": "r1"}),
        _env(EventType.RUN_CANCELLED, {"reason": "user"}),
    ]))
    assert frames[-1] == "[DONE]"
    last = [f for f in frames if f != "[DONE]"][-1]
    assert last["choices"][0]["finish_reason"] == "stop"
