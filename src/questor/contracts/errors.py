"""L0 错误信封与分类类型（design/01 §8；ADR-0010）。

ADR-0010 的分层归属：**分类是纯函数、留在 contracts（不 import provider）**；
重试/fallback 的编排归 Kernel。P0/P1 先固定「形状」——分类器实际填充发生在错误
真正流动的 P1+ / P10。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from questor.contracts.common import JsonObject, require_aware


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
