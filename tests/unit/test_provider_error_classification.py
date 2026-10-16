"""L0 provider 错误分类纯函数（ADR-0028；plan/01 T4「错误归一为 ErrorEntry」的接线）。

为什么单列测试：分类是 **ADR-0010 归 contracts 的纯函数**，Kernel 只在 provider 边界消费它的
verdict。表里每条都必须能判红——特别是"配对违规 400 属 format_error 且**不可重试**"：若它被判
retryable=True，P10 接上退避重试后会把同一个确定性错误原样打满预算（ADR-0028 §后果）。

诚实边界：本表只做 kernel 现在需要的粗分类；design/04 §13 规划的"有序阶段优先级表 +
多 hint 全量分类"仍归 P10（plan/01 §1.2 后置项）。
"""

from __future__ import annotations

from questor.contracts.errors import ErrorKind, ErrorLayer, classify_provider_error


class _StatusError(Exception):
    """模拟 openai/litellm 侧带 ``status_code`` 的 API 异常形状。"""

    def __init__(self, status_code: int, message: str = "provider said no") -> None:
        super().__init__(message)
        self.status_code = status_code


def test_pairing_violation_400_is_format_error_and_not_retryable() -> None:
    exc = RuntimeError(
        "Error code: 400 - An assistant message with 'tool_calls' must be followed by "
        "tool messages responding to each 'tool_call_id'. (insufficient tool messages)"
    )
    entry = classify_provider_error(exc, at_turn=2)
    assert entry.layer is ErrorLayer.PROVIDER
    assert entry.kind is ErrorKind.FORMAT_ERROR
    # 这条必须是 False：配对违规由我们发出的历史决定，重试只会原样再失败。
    assert entry.hints.retryable is False
    assert entry.at_turn == 2
    assert entry.cause == "RuntimeError"


def test_status_codes_map_to_stable_kinds() -> None:
    cases = {
        400: ErrorKind.FORMAT_ERROR,
        401: ErrorKind.AUTH,
        402: ErrorKind.BILLING,
        403: ErrorKind.AUTH,
        404: ErrorKind.MODEL_NOT_FOUND,
        408: ErrorKind.TIMEOUT,
        429: ErrorKind.RATE_LIMIT,
        500: ErrorKind.CONNECTION,
        503: ErrorKind.CONNECTION,
    }
    for status, expected in cases.items():
        assert classify_provider_error(_StatusError(status), at_turn=1).kind is expected, status


def test_retryable_verdicts_split_transient_from_deterministic() -> None:
    transient = (408, 429, 500, 503)
    deterministic = (400, 401, 402, 403, 404)
    for status in transient:
        assert classify_provider_error(_StatusError(status), at_turn=1).hints.retryable is True, status
    for status in deterministic:
        assert classify_provider_error(_StatusError(status), at_turn=1).hints.retryable is False, status


def test_payload_too_large_asks_for_compression_not_retry() -> None:
    entry = classify_provider_error(_StatusError(413, "payload too large"), at_turn=1)
    assert entry.kind is ErrorKind.PAYLOAD_TOO_LARGE
    assert entry.hints.retryable is False
    # 压缩是 P10 的活路，hint 先给对（design/01 §8：重试/fallback 读 hint）。
    assert entry.hints.should_compress is True


def test_message_patterns_cover_status_less_gateways() -> None:
    # 不少兼容网关把状态码吞在消息里（litellm 有时只重抛消息），模式兜底防漏判。
    assert classify_provider_error(RuntimeError("Invalid request: insufficient tool messages"), at_turn=1).kind is ErrorKind.FORMAT_ERROR
    assert classify_provider_error(RuntimeError("Too many requests, rate limit reached"), at_turn=1).kind is ErrorKind.RATE_LIMIT
    assert classify_provider_error(RuntimeError("Request timed out"), at_turn=1).kind is ErrorKind.TIMEOUT
    assert classify_provider_error(RuntimeError("Connection reset by peer"), at_turn=1).kind is ErrorKind.CONNECTION
    assert classify_provider_error(RuntimeError("maximum context length is 8192 tokens"), at_turn=1).kind is ErrorKind.CONTEXT_OVERFLOW
    assert classify_provider_error(RuntimeError("model not found: gpt-9"), at_turn=1).kind is ErrorKind.MODEL_NOT_FOUND


def test_unknown_error_fails_closed_as_non_retryable() -> None:
    entry = classify_provider_error(ValueError("something odd happened"), at_turn=3)
    assert entry.kind is ErrorKind.UNKNOWN
    # 不可确认 ⇒ 不重试：宁可少重试一次，也不把预算烧在确定性错误上。
    assert entry.hints.retryable is False


def test_classifier_never_raises_on_hostless_objects() -> None:
    """分类器自己出问题时也必须出声为 UNKNOWN，绝不能把错误路径变成第二个异常（参照 hermes
    error_surface 的"NEVER raises"纪律，MIT © Nous Research，改造复用形状非照搬）。"""

    class _Evil:
        @property
        def status_code(self) -> int:  # noqa: D102 - 故意抛
            raise RuntimeError("boom in attribute access")

    entry = classify_provider_error(_Evil(), at_turn=1)  # type: ignore[arg-type]
    assert entry.kind is ErrorKind.UNKNOWN
    assert entry.hints.retryable is False


def test_message_is_bounded_to_wire_cap() -> None:
    # protocol/event.schema.json 的 run_failed.error.message maxLength=8192：超限会让整条终态事件不合法。
    entry = classify_provider_error(RuntimeError("x" * 20000), at_turn=1)
    assert len(entry.message) <= 8192
