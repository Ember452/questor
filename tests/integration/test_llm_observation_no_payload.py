"""DoD B⑤：LLM 观测面零原文（DESIGN §12；ADR-0027 D4）。

``LiteLLMProvider.stream`` 每次调用结束（成功/失败）产一条 ``questor.llm`` 行，携
``provider/model/duration_ms/status/finish_reason/prompt_tokens/completion_tokens/
request_sha256/response_sha256/error_class``，**绝不含 prompt/响应原文**。monkeypatch
``litellm.acompletion`` 回放假 chunk，捕获 stdlib 记录里的 ``log_fields`` 断言。
"""

from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from questor.contracts.ports import ProviderRequest
from questor.contracts.state_schema import ContentBlock, Message, Role
from questor.providers import litellm_adapter

_SENTINEL = "SECRET-PROMPT-SENTINEL-abc123"
_REQUIRED = {
    "provider",
    "model",
    "duration_ms",
    "status",
    "finish_reason",
    "prompt_tokens",
    "completion_tokens",
    "request_sha256",
    "response_sha256",
    "error_class",
}


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _request() -> ProviderRequest:
    msg = Message(id="m1", role=Role.USER, content=(ContentBlock(type="text", text=_SENTINEL),), seq=0)
    return ProviderRequest(model="gpt-test", messages=(msg,))


def _fake_chunks() -> list[Any]:
    usage = SimpleNamespace(choices=None, usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18})
    text = SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="hi there", tool_calls=None), finish_reason=None)], usage=None)
    done = SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="", tool_calls=None), finish_reason="stop")], usage=None)
    return [usage, text, done]


async def _drain(provider: litellm_adapter.LiteLLMProvider, request: ProviderRequest) -> None:
    async for _ in provider.stream(request):
        pass


@pytest.fixture
def llm_capture(monkeypatch):  # noqa: ANN201
    cap = _Capture()
    llm_logger = logging.getLogger("questor.llm")
    llm_logger.addHandler(cap)
    llm_logger.setLevel(logging.DEBUG)
    prev = llm_logger.propagate
    llm_logger.propagate = False
    yield cap, monkeypatch
    llm_logger.removeHandler(cap)
    llm_logger.propagate = prev


def test_llm_row_has_all_fields_and_no_prompt(llm_capture) -> None:  # noqa: ANN001
    cap, monkeypatch = llm_capture

    async def fake_acompletion(**kwargs):  # noqa: ANN003, ANN202
        return _iter(_fake_chunks())

    async def _iter(chunks):  # noqa: ANN001, ANN202
        for c in chunks:
            yield c

    monkeypatch.setattr(litellm_adapter.litellm, "acompletion", fake_acompletion)
    asyncio.run(_drain(litellm_adapter.LiteLLMProvider("gpt-test"), _request()))

    assert cap.records, "expected a questor.llm row"
    fields = getattr(cap.records[0], "log_fields", {})
    assert _REQUIRED <= set(fields), f"missing: {_REQUIRED - set(fields)}"
    assert fields["status"] == "ok"
    assert fields["finish_reason"] == "stop"
    assert fields["prompt_tokens"] == 11 and fields["completion_tokens"] == 7
    # 零原文：请求/响应只落 sha256，绝不落 prompt 片段。
    blob = json.dumps(fields, default=str) + cap.records[0].getMessage()
    assert _SENTINEL not in blob, "prompt sentinel leaked into llm log row"
    assert len(fields["request_sha256"]) == 64 and len(fields["response_sha256"]) == 64


def test_llm_row_emitted_on_error(llm_capture) -> None:  # noqa: ANN001
    cap, monkeypatch = llm_capture

    async def boom(**kwargs):  # noqa: ANN003, ANN202
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(litellm_adapter.litellm, "acompletion", boom)
    with pytest.raises(RuntimeError):
        asyncio.run(_drain(litellm_adapter.LiteLLMProvider("gpt-test"), _request()))

    assert cap.records, "error path must still emit a questor.llm row"
    fields = getattr(cap.records[-1], "log_fields", {})
    assert fields["status"] == "error"
    assert fields["error_class"] == "RuntimeError"
