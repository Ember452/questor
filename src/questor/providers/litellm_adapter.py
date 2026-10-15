"""L5 ProviderPort -> LiteLLM 流式适配器（ADR-0002）。

产出归一化的 ``StreamChunk`` 交内核定稿：text / reasoning / tool_call 片段 / usage /
finish。按 R08 C 处理若干坑：usage 只要出现就读（不假设只在末块）、reasoning 多别名
归一、tool_call 的参数分片按 index 透传交内核累积。``litellm`` 只在此 import
（ruff banned-api 对 providers/* 豁免）。
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

# reasoning/thinking 在不同 provider 字段名各异，统一按这些键探测归一。
_REASONING_KEYS = ("reasoning_content", "reasoning", "thinking")


def _content_text(message: Message) -> str:
    """拼接消息里所有可见 text 块。"""
    return "".join(b.text or "" for b in message.content if b.type == "text")


def to_openai_messages(messages: tuple[Message, ...], system: str | None) -> list[dict[str, Any]]:
    """把 Domain_State 消息投影为 OpenAI 形状（只读，不改状态）。

    tool_result 走 role=tool；assistant 的 tool_use 走 tool_calls；其余按角色直投。
    """
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
    """把 ToolSpec 转为 OpenAI function tools 形状。"""
    return [
        {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": dict(t.params)}}
        for t in tools
    ]


class LiteLLMProvider(ProviderPort):
    """经 LiteLLM 的真实模型适配器（BYOM/多供应商经 model + settings 配置）。"""

    def __init__(self, model: str, **settings: Any) -> None:
        self.model = model
        self.settings = settings

    async def stream(self, request: ProviderRequest) -> AsyncIterator[StreamChunk]:
        """流式请求并把原始 chunk 归一化为 StreamChunk 序列。"""
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
    """从多别名里取第一个非空 reasoning 文本。"""
    for key in _REASONING_KEYS:
        value = getattr(delta, key, None)
        if value:
            return str(value)
    return None


def _usage_dict(usage: Any) -> JsonObject:
    """把 usage 归一为 dict（对象形态取属性）。"""
    if isinstance(usage, dict):
        return usage
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", 0),
        "completion_tokens": getattr(usage, "completion_tokens", 0),
        "total_tokens": getattr(usage, "total_tokens", 0),
    }
