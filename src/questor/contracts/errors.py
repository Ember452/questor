"""L0 错误信封与分类类型（design/01 §8；ADR-0010）。

ADR-0010 的分层归属：**分类是纯函数、留在 contracts（不 import provider）**；重试/fallback 的
编排归 Kernel。``classify_provider_error`` 就是 Kernel 在 provider 边界消费的粗分类（ADR-0028：
plan/01 T4「错误归一为 ErrorEntry」到此接线）——只回答「归哪个 kind + 可不可重试 + 该不该压缩」。

诚实边界：design/04 §13 规划的「有序阶段优先级表 + 全量多 hint 分类」（memory-ceiling 优先于
overflow、凭据轮换、fallback 判定）仍归 P10 加固期（plan/01 §1.2 后置项）；本表刻意只覆盖 kernel
现在真需要的分支，不留无人消费的控制位（P2 审计 A 类「假扩展位」缺陷的反面教训）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from questor.contracts.common import JsonObject, require_aware, utc_now


class ErrorLayer(StrEnum):
    """错误发生的层次，用于把问题定位到具体子系统。"""

    KERNEL = "kernel"
    TOOL = "tool"
    PROVIDER = "provider"
    PERSIST = "persist"


class ErrorKind(StrEnum):
    """稳定、与供应商无关的错误命名空间（对外 ``error.code`` 的取值域）。"""

    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    RATE_LIMIT = "rate_limit"
    CONTEXT_OVERFLOW = "context_overflow"
    CONTEXT_MEMORY_CEILING = "context_memory_ceiling"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    FORMAT_ERROR = "format_error"
    UNSUPPORTED_MODALITY = "unsupported_modality"  # P9/ADR-0044：非文本/语音 content part 归一拒绝（承 ADR-0036 决策5），不可重试
    AUTH = "auth"
    BILLING = "billing"
    MODEL_NOT_FOUND = "model_not_found"
    CANCELLED = "cancelled"
    POLICY_VIOLATION = "policy_violation"
    INTERNAL = "internal"


@dataclass(frozen=True, slots=True)
class RecoveryHints:
    """正交的恢复开关（R08 A-1），而非单一的 ``retryable`` 布尔。

    为什么要拆多维：一次失败的处置往往是多轴组合（重试 / 压缩 / 换模型 / 换凭据），
    用布尔位表达能让上层策略显式决策。P0/P1 默认全 False，真正的分类器在 P10 加固期填充。
    """

    retryable: bool = False
    should_compress: bool = False
    should_fallback: bool = False
    should_rotate_credential: bool = False


@dataclass(frozen=True, slots=True)
class ErrorEntry:
    """归一化并记录到 ``run.error_stack`` 的单条错误（design/01 §8）。"""

    kind: ErrorKind
    layer: ErrorLayer
    message: str
    at_turn: int
    hints: RecoveryHints
    seq: int | None = None
    timestamp: datetime | None = None
    cause: str | None = None
    context: JsonObject | None = None
    resumable: bool = False  # 与 retryable 正交：能否带上下文人工复活（R08 E-5）

    def __post_init__(self) -> None:
        # 时间戳必须带时区：错误栈要能回放/跨进程对齐（R03 B-P3）。
        if self.timestamp is not None:
            require_aware(self.timestamp, "ErrorEntry.timestamp")


#: ``ErrorEntry.message`` 的字符上限，与 ``protocol/event.schema.json`` 里
#: ``run_failed.error.message`` 的 ``maxLength`` 同步（HARD C15：单一真源、超限会让整条
#: 终态事件不合法，从而把「出错」升级成「协议违规」）。
MAX_ERROR_MESSAGE_CHARS = 8192

#: 状态码 → (kind, retryable, should_compress)。4xx 里确定性拒绝**一律不可重试**：
#: 同样的请求重发一次只会同样失败，把预算烧光（ADR-0028 §后果）。413 例外地给
#: ``should_compress``：正文超限的唯一活路是压缩，而压缩本身归 P10。
_STATUS_VERDICTS: dict[int, tuple[ErrorKind, bool, bool]] = {
    400: (ErrorKind.FORMAT_ERROR, False, False),
    401: (ErrorKind.AUTH, False, False),
    402: (ErrorKind.BILLING, False, False),
    403: (ErrorKind.AUTH, False, False),
    404: (ErrorKind.MODEL_NOT_FOUND, False, False),
    408: (ErrorKind.TIMEOUT, True, False),
    413: (ErrorKind.PAYLOAD_TOO_LARGE, False, True),
    422: (ErrorKind.FORMAT_ERROR, False, False),
    429: (ErrorKind.RATE_LIMIT, True, False),
}

#: 有序消息模式表（**先匹配先赢**，故把最具体的配对/超限类放前面）。兼容网关常把状态码
#: 吞在消息里（litellm 有时只重抛文本），没有这张表就会漏判成 UNKNOWN 而错过重试判据。
_PATTERN_VERDICTS: tuple[tuple[tuple[str, ...], ErrorKind, bool, bool], ...] = (
    # tool_use↔tool_result 配对违规：本次崩溃的直接形状，属我们发出的历史非法——确定性错误。
    (("must be followed by", "insufficient tool messages", "unresolved tool", "tool_call_id"), ErrorKind.FORMAT_ERROR, False, False),
    (("maximum context length", "context length exceeded", "too many tokens", "reduce the length"), ErrorKind.CONTEXT_OVERFLOW, False, True),
    (("rate limit", "too many requests", "throttl"), ErrorKind.RATE_LIMIT, True, False),
    (("timeout", "timed out", "deadline exceeded"), ErrorKind.TIMEOUT, True, False),
    (("connection", "network", "unreachable", "reset by peer", "eof occurred"), ErrorKind.CONNECTION, True, False),
    (("invalid api key", "unauthorized", "forbidden", "incorrect api key"), ErrorKind.AUTH, False, False),
    (("model not found", "invalid model", "no such model", "does not exist"), ErrorKind.MODEL_NOT_FOUND, False, False),
)

# litellm 把自己的 HTTP 状态拼进异常文本（``Error code: 429 - …``），这是第三号状态码来源。
_STATUS_IN_MESSAGE = re.compile(r"error code:\s*(\d{3})", re.IGNORECASE)


def _verdict_of(exc: BaseException) -> tuple[ErrorKind, bool, bool]:
    """按「显式状态码 → 消息里的 ``Error code: NNN`` → 有序模式表」三段求值；默认 fail-closed。

    为什么默认不可重试：确认不了的错误宁可少重试一次，也不能把确定性失败打成预算耗尽
    （design/04 §13 的 fail-to-builtin 同口径）。5xx 一律 CONNECTION 可重试（供应商侧抖动）。
    """
    message = str(exc)
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int) or isinstance(status, bool):  # bool 是 int 子类：显式排除，别让 True 当状态码
        match = _STATUS_IN_MESSAGE.search(message)
        status = int(match.group(1)) if match else None
    if isinstance(status, int):
        if status >= 500:
            return ErrorKind.CONNECTION, True, False
        verdict = _STATUS_VERDICTS.get(status)
        if verdict is not None:
            return verdict
    lowered = message.lower()
    for fragments, kind, retryable, compress in _PATTERN_VERDICTS:
        if any(fragment in lowered for fragment in fragments):
            return kind, retryable, compress
    return ErrorKind.UNKNOWN, False, False


def classify_provider_error(exc: BaseException, *, at_turn: int) -> ErrorEntry:
    """把 provider 边界的异常归一为 ``ErrorEntry``（design/01 §8 的 envelope；ADR-0028）。

    怎么用：Kernel 在包裹 ``ProviderPort.stream`` 的唯一边界调用它，拿到 entry 后走
    ``FinalizeRun(failed)``——**绝不允许异常穿出 turn 循环**（C10 的 provider 侧对称面）。
    依赖：纯函数，只读异常对象，不 import provider/litellm（ADR-0010；C1）。
    不变式：返回值永不为 ``None``；``layer`` 恒为 ``PROVIDER``（调用点即故障域）；
    ``message`` 有界到 :data:`MAX_ERROR_MESSAGE_CHARS`。
    失败语义：**本函数绝不抛**——分类器自己出错时降级为 ``UNKNOWN``/不可重试，
    免得错误路径变成第二个异常把 run 打穿（参照 hermes ``agent/error_surface.py`` 的
    "NEVER raises" 纪律，MIT © Nous Research；改造复用其形状，非照搬实现）。
    """
    try:
        kind, retryable, should_compress = _verdict_of(exc)
        message = str(exc) or type(exc).__name__
        cause = type(exc).__name__
    except Exception:  # noqa: BLE001 - 错误分类自身故障不得变成第二个异常
        kind, retryable, should_compress = ErrorKind.UNKNOWN, False, False
        message, cause = "provider error classification failed", "ClassificationFailure"
    return ErrorEntry(
        kind=kind,
        layer=ErrorLayer.PROVIDER,
        message=message[:MAX_ERROR_MESSAGE_CHARS],
        at_turn=at_turn,
        hints=RecoveryHints(retryable=retryable, should_compress=should_compress),
        cause=cause,
        timestamp=utc_now(),
    )
