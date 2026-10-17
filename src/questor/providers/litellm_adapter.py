"""L5 ProviderPort -> LiteLLM 流式适配器（ADR-0002）。

产出归一化的 ``StreamChunk`` 交内核定稿：text / reasoning / tool_call 片段 / usage /
finish。按 R08 C 处理若干坑：usage 只要出现就读（不假设只在末块）、reasoning 多别名
归一、tool_call 的参数分片按 index 透传交内核累积。``litellm`` 只在此 import
（ruff banned-api 对 providers/* 豁免）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import litellm

from questor.contracts.common import JsonObject, thaw
from questor.contracts.ports import ProviderPort, ProviderRequest, StreamChunk
from questor.contracts.state_schema import Message, Role
from questor.contracts.tool import ToolSpec

# reasoning/thinking 在不同 provider 字段名各异，统一按这些键探测归一。
_REASONING_KEYS = ("reasoning_content", "reasoning", "thinking")

#: LLM 观测行 logger（DESIGN §12）：经带内桥进 pipeline。取 **DEBUG** 级——console（INFO 门）
#: 不收、主干文件（DEBUG）收元数据、llm 通道独立承载（DESIGN §12/§10）。**零原文**：只落
#: sha256 + token 计数 + 耗时 + 分类，绝不落 prompt/响应片段（DoD B⑤；ADR-0027 D4）。
_LLM_LOG = logging.getLogger("questor.llm")


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
        """流式请求并把原始 chunk 归一化为 StreamChunk 序列。

        每次调用结束（成功/失败/取消）在 ``finally`` 产一条 ``questor.llm`` 观测行（DoD B⑤）：
        观测是只读旁路，**不吞故障**——异常记 ``status=error`` 后原样上冒，交 loop 的统一边界归一。
        """
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

        started = time.monotonic()
        status = "ok"
        error_class: str | None = None
        finish_reason: str | None = None
        prompt_tokens = 0
        completion_tokens = 0
        resp_parts: list[str] = []
        # 请求 sha256 在对**完整 params**（含 messages）做规范化哈希后即丢弃原文——只留摘要用于辨识
        # “是否同一请求”（DESIGN §12），落盘的永远不含 prompt。
        request_sha256 = hashlib.sha256(
            json.dumps(params, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
        ).hexdigest()
        try:
            async for chunk in await litellm.acompletion(**params):  # type: ignore[arg-type]
                usage = getattr(chunk, "usage", None)
                if usage:
                    usage_dict = _usage_dict(usage)
                    prompt_tokens = usage_dict.get("prompt_tokens", 0) or prompt_tokens
                    completion_tokens = usage_dict.get("completion_tokens", 0) or completion_tokens
                    yield StreamChunk(kind="usage", usage=usage_dict)
                choices = getattr(chunk, "choices", None)
                if not choices:
                    continue
                choice = choices[0]
                delta = choice.delta
                reasoning = _delta_reasoning(delta)
                if reasoning:
                    resp_parts.append(reasoning)
                    yield StreamChunk(kind="reasoning", text=reasoning)
                if getattr(delta, "content", None):
                    resp_parts.append(delta.content)
                    yield StreamChunk(kind="text", text=delta.content)
                for tc in getattr(delta, "tool_calls", None) or []:
                    fn = getattr(tc, "function", None)
                    args_delta = getattr(fn, "arguments", None) or ""
                    resp_parts.append(args_delta)
                    yield StreamChunk(
                        kind="tool_call",
                        tool_call={
                            "index": tc.index,
                            "id": tc.id,
                            "name": getattr(fn, "name", None),
                            "args_delta": args_delta,
                        },
                    )
                if getattr(choice, "finish_reason", None):
                    finish_reason = choice.finish_reason
                    yield StreamChunk(kind="finish", finish_reason=finish_reason)
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        except Exception as exc:  # noqa: BLE001 - 观测不吞：记 status=error 后原样上冒（CancelledError 属 BaseException 已先走上一分支）
            status = "error"
            error_class = type(exc).__name__
            raise
        finally:
            response_sha256 = hashlib.sha256("".join(resp_parts).encode("utf-8")).hexdigest()
            _emit_llm_observation(
                model=request.model or self.model,
                status=status,
                error_class=error_class,
                finish_reason=finish_reason,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                duration_ms=int((time.monotonic() - started) * 1000),
                request_sha256=request_sha256,
                response_sha256=response_sha256,
            )


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


def _emit_llm_observation(
    *,
    model: str,
    status: str,
    error_class: str | None,
    finish_reason: str | None,
    prompt_tokens: int,
    completion_tokens: int,
    duration_ms: int,
    request_sha256: str,
    response_sha256: str,
) -> None:
    """产一条 ``questor.llm`` DEBUG 行（DESIGN §12；DoD B⑤）。

    经 ``extra={"log_fields": {...}`` 白名单入口携元数据（桥只透传此键，禁透传任意 record 属性）；
    值全为标量，落盘 JSONL 无 prompt/响应原文。``msg`` 只含 status 一词，绝不掺入内容。
    """
    fields: dict[str, str | int | None] = {
        "provider": model.split("/", 1)[0] if "/" in model else "unknown",
        "model": model,
        "duration_ms": duration_ms,
        "status": status,
        "finish_reason": finish_reason,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "request_sha256": request_sha256,
        "response_sha256": response_sha256,
        "error_class": error_class,
    }
    _LLM_LOG.debug("llm %s", status, extra={"log_fields": fields})
