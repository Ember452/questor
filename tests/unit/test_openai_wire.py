"""P9 T6a/T7：OpenAI wire 契约（contracts/openai_wire.py）——请求解析 + 非文本归一拒绝 + chunk/error builder。

wire 是独立契约（ADR-0043），与 questor 事件契约分离。非文本/语音 part → 归一化拒绝
（ADR-0044：不起 run、不崩、不静默降级）。本测钉纯函数面；HTTP 端点投影归 T6c。
"""

from __future__ import annotations

import pytest

from questor.contracts.errors import ErrorKind
from questor.contracts.openai_wire import (
    OpenAIRequestError,
    error_object,
    extract_last_user_text,
    make_chunk,
)


def test_extract_user_text_from_plain_string_content() -> None:
    messages = [{"role": "user", "content": "hello"}]
    assert extract_last_user_text(messages) == "hello"


def test_extract_user_text_from_list_text_parts() -> None:
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]},
    ]
    assert extract_last_user_text(messages) == "ab"


def test_non_text_image_part_is_rejected() -> None:
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "look"}, {"type": "image_url", "image_url": {"url": "http://x"}}]},
    ]
    with pytest.raises(OpenAIRequestError) as exc:
        extract_last_user_text(messages)
    assert exc.value.code == "unsupported_modality"
    assert exc.value.http_status == 400


def test_input_audio_part_is_rejected() -> None:
    messages = [{"role": "user", "content": [{"type": "input_audio", "input_audio": {"data": "..."}}]}]
    with pytest.raises(OpenAIRequestError) as exc:
        extract_last_user_text(messages)
    assert exc.value.code == "unsupported_modality"


def test_missing_user_message_is_invalid_request() -> None:
    with pytest.raises(OpenAIRequestError) as exc:
        extract_last_user_text([{"role": "system", "content": "sys"}])
    assert exc.value.code == "invalid_request"


def test_last_user_message_wins() -> None:
    messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": "second"},
    ]
    assert extract_last_user_text(messages) == "second"


def test_make_delta_chunk_shape() -> None:
    chunk = make_chunk("chatcmpl-1", 1700000000, "questor", {"content": "hi"})
    assert chunk["object"] == "chat.completion.chunk"
    assert chunk["id"] == "chatcmpl-1"
    assert chunk["choices"][0]["delta"] == {"content": "hi"}
    assert chunk["choices"][0]["finish_reason"] is None
    assert chunk["choices"][0]["index"] == 0


def test_make_final_chunk_has_finish_reason() -> None:
    chunk = make_chunk("chatcmpl-1", 1700000000, "questor", {}, finish_reason="stop")
    assert chunk["choices"][0]["finish_reason"] == "stop"


def test_x_questor_extension_is_separate_from_openai_standard_fields() -> None:
    chunk = make_chunk("chatcmpl-1", 1700000000, "questor", {"content": "x"}, x_questor={"run_id": "r1"})
    assert chunk["x_questor"] == {"run_id": "r1"}
    # 标准字段不被专有扩展污染。
    assert "run_id" not in chunk["choices"][0]["delta"]


def test_error_object_shape() -> None:
    err = error_object("unsupported_modality", "provider capability not supported: image_url")
    assert err["error"]["code"] == "unsupported_modality"
    assert err["error"]["type"] == "invalid_request_error"
    assert "image_url" in err["error"]["message"]


def test_unsupported_modality_error_kind_added() -> None:
    # additive ErrorKind（ADR-0044）：稳定错误命名空间增量、不破既有 kind。
    assert ErrorKind.UNSUPPORTED_MODALITY == "unsupported_modality"
