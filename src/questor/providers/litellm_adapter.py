"""L5 ProviderPort -> LiteLLM streaming adapter (ADR-0002).

Emits normalized ``StreamChunk``s for the kernel to assemble: text / reasoning /
tool_call fragments / usage / finish. Pitfalls handled per R08 C: usage is read
whenever present (not assumed last-chunk-only), reasoning aliases are normalized,
and tool-call argument fragments are passed through by index for the kernel to
accumulate. ``litellm`` is imported only here (ruff banned-api exempts providers/*).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import litellm

from questor.contracts.common import JsonObject, thaw
from questor.contracts.ports import ProviderPort, ProviderRequest, StreamChunk
from questor.contracts.state_schema import Message, Role
from questor.contracts.tool import ToolSpec

_REASONING_KEYS = ("reasoning_content", "reasoning", "thinking")


def _content_text(message: Message) -> str:
    return "".join(b.text or "" for b in message.content if b.type == "text")


def to_openai_messages(messages: tuple[Message, ...], system: str | None) -> list[dict[str, Any]]:
    """Project Domain_State messages into OpenAI-shaped dicts (read-only)."""
    out: list[dict[str, Any]] = []
    if system:
        out.append({"role": "system", "content": system})
    for m in messages:
        if m.role is Role.TOOL:
            for b in m.content:
                if b.type == "tool_result":
                    out.append({"role": "tool", "tool_call_id": b.tool_use_id, "content": b.text or ""})
        else:
            tool_calls = [
                {"id": b.tool_use_id, "type": "function", "function": {"name": b.name, "arguments": json.dumps(thaw(b.input or {}))}}
                for b in m.content
                if b.type == "tool_use"
            ]
            entry: dict[str, Any] = {"role": m.role.value, "content": _content_text(m) or (None if tool_calls else "")}
            if tool_calls:
                entry["tool_calls"] = tool_calls
            out.append(entry)
    return out


def tools_to_openai(tools: tuple[ToolSpec, ...]) -> list[dict[str, Any]]:
    return [
        {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": dict(t.params)}}
        for t in tools
    ]


class LiteLLMProvider(ProviderPort):
    def __init__(self, model: str, **settings: Any) -> None:
        self.model = model
        self.settings = settings

    async def stream(self, request: ProviderRequest) -> AsyncIterator[StreamChunk]:
        params: JsonObject = {
            "model": request.model or self.model,
            "messages": to_openai_messages(request.messages, request.system),
            "stream": True,
            "stream_options": {"include_usage": True},
            **self.settings,
            **(request.settings or {}),
        }
        if request.tools:
            params["tools"] = tools_to_openai(request.tools)

        async for chunk in await litellm.acompletion(**params):  # type: ignore[arg-type]
            usage = getattr(chunk, "usage", None)
            if usage:
                yield StreamChunk(kind="usage", usage=_usage_dict(usage))
            choices = getattr(chunk, "choices", None)
            if not choices:
                continue
            choice = choices[0]
            delta = choice.delta
            reasoning = _delta_reasoning(delta)
            if reasoning:
                yield StreamChunk(kind="reasoning", text=reasoning)
            if getattr(delta, "content", None):
                yield StreamChunk(kind="text", text=delta.content)
            for tc in getattr(delta, "tool_calls", None) or []:
                fn = getattr(tc, "function", None)
                yield StreamChunk(
                    kind="tool_call",
                    tool_call={
                        "index": tc.index,
                        "id": tc.id,
                        "name": getattr(fn, "name", None),
                        "args_delta": getattr(fn, "arguments", None) or "",
                    },
                )
            if getattr(choice, "finish_reason", None):
                yield StreamChunk(kind="finish", finish_reason=choice.finish_reason)


def _delta_reasoning(delta: Any) -> str | None:
    for key in _REASONING_KEYS:
        value = getattr(delta, key, None)
        if value:
            return str(value)
    return None


def _usage_dict(usage: Any) -> JsonObject:
    if isinstance(usage, dict):
        return usage
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", 0),
        "completion_tokens": getattr(usage, "completion_tokens", 0),
        "total_tokens": getattr(usage, "total_tokens", 0),
    }
