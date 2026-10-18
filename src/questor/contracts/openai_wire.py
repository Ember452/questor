"""L0 OpenAI 兼容 wire 契约（Python 侧权威形状；ADR-0043）。

**独立契约**：OpenAI 的 ``/v1/chat/completions`` 请求体 + ``chat.completion.chunk`` 响应是业界
协议，与 questor 自有事件契约（``protocol/event.schema.json``）**分道**——questor 事件契约不收
任何 OpenAI 形状、``v`` 不 bump（C15 单一真源各管各的）。wire 漂移由 ``scripts/check_openai_compat_schema.py``
（T9）对 ``protocol/openai_compat.schema.json`` 守护，本模块是 Python 侧的构造/解析权威。

本模块只放**纯数据 + 纯函数**（请求解析、chunk/error 构造），不含 HTTP/IO——投影适配器与鉴权
lane 住在 ``surfaces/openai_compat.py``（L6）。非文本/语音 content part 在此**归一化拒绝**
（ADR-0044：不起 run、不崩、不静默降级成纯文本）。
"""

from __future__ import annotations

from typing import Any

#: questor 当前仅文本模态（ADR-0036 移除 P6）：入站 content part 只接受 ``type=="text"``，
#: 其余（image_url/input_audio/audio/file/video/未知）一律归一拒绝。
_TEXT_PART_TYPE = "text"


class OpenAIRequestError(Exception):
    """入站请求校验失败（surface fail-fast，**不起 run**）。``code`` 进 OpenAI error object。

    这是协议级输入校验（适配器边界、非状态写），故不触 C16/C14——只拒、不改内核状态。"""

    def __init__(self, code: str, message: str, *, param: str | None = None, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.param = param
        self.http_status = http_status


def _parts_to_text(content: Any) -> str:
    """把一条消息的 content（str 或 OpenAI parts 列表）取为纯文本；非文本 part → 归一拒绝。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        buf: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                raise OpenAIRequestError("invalid_request", "malformed content part (expected object)", param="messages")
            part_type = part.get("type")
            if part_type == _TEXT_PART_TYPE:
                buf.append(part.get("text") or "")
            else:
                # 宁可拒不误降级：任何非 text（含未知 type）都归一拒绝（ADR-0044）。
                raise OpenAIRequestError(
                    "unsupported_modality",
                    f"provider capability not supported: content part type {part_type!r}",
                    param="messages",
                )
        return "".join(buf)
    raise OpenAIRequestError("invalid_request", "content must be a string or a list of parts", param="messages")


def extract_last_user_text(messages: Any) -> str:
    """取最后一条 ``role=="user"`` 消息的文本作为本轮 SubmitMessage 输入。

    失败语义：无 user 消息 / 非 list / 含非文本 part → :class:`OpenAIRequestError`（surface 层拒、不起 run）。"""
    if not isinstance(messages, list):
        raise OpenAIRequestError("invalid_request", "messages must be a list", param="messages")
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "user":
            return _parts_to_text(message.get("content"))
    raise OpenAIRequestError("invalid_request", "no user message in request", param="messages")


def make_chunk(
    completion_id: str,
    created: int,
    model: str,
    delta: dict[str, Any],
    *,
    finish_reason: str | None = None,
    x_questor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造一帧 ``chat.completion.chunk``：标准字段走 OpenAI 语义，专有只进 ``x_questor``（design/02 §10）。"""
    chunk: dict[str, Any] = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    if x_questor is not None:
        chunk["x_questor"] = x_questor
    return chunk


def error_object(code: str, message: str, *, error_type: str = "invalid_request_error", param: str | None = None) -> dict[str, Any]:
    """构造 OpenAI 错误体：``{"error": {type, message, param, code}}``。"""
    return {"error": {"type": error_type, "message": message, "param": param, "code": code}}


__all__ = [
    "OpenAIRequestError",
    "error_object",
    "extract_last_user_text",
    "make_chunk",
]
