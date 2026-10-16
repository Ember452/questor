"""L0 词汇层共享原语（不依赖 UI）。

 adapted 自 DeepCode ``core/domain/common.py`` 的思路（仅借鉴形状、非逐行照搬），
 保持依赖极简（标准库 + immutables）。这些是 ``contracts`` 与 ``state`` 共用的
 不变式助手：类型化 id、时区感知时间戳、JSON 安全校验、深冻结。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import immutables

#: JSON 对象的类型别名（映射语义，运行时可能是 dict 或 immutables.Map）。
JsonObject = Mapping[str, Any]


def freeze(value: Any) -> Any:
    """把任意 JSON 值递归冻结为不可变容器。

    为什么要深冻结：``dataclass(frozen=True)`` 只挡最外层 setattr，内层 dict/list
    仍可原地改；而 COW 会让新旧状态共享同一叶容器（HARD C2）。故 dict→immutables.Map、
    list/tuple→tuple，逐层递归，确保被共享的叶无法被就地篡改、从而不污染可回放的历史。
    """
    if isinstance(value, Mapping) and not isinstance(value, immutables.Map):
        return immutables.Map({k: freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(v) for v in value)
    return value


def thaw(value: Any) -> Any:
    """:func:`freeze` 的逆操作：还原为普通 dict/list，供 JSON 序列化使用。"""
    if isinstance(value, Mapping):
        return {k: thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [thaw(v) for v in value]
    return value


def utc_now() -> datetime:
    """返回带时区的 UTC 时间戳（永不 naive），避免落库时间歧义。"""
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    """生成带类型前缀的不透明 id（如 ``run_ab12…``）。

    校验前缀为非空 ASCII 字母数字：id 是跨事件/持久层的关联键，必须可安全嵌入 SQL 与
    比对（``require_prefixed_id`` 依赖此前缀约定）。
    """
    if not prefix or not prefix.isascii() or not prefix.replace("_", "").isalnum():
        raise ValueError("identifier prefix must be non-empty ASCII alphanumeric")
    return f"{prefix}_{uuid.uuid4().hex}"


def require_prefixed_id(value: str, prefix: str) -> None:
    """断言 ``value`` 形如 ``{prefix}_…``；用于校验关联键的类型前缀。"""
    if (
        not isinstance(value, str)
        or not value.startswith(f"{prefix}_")
        or len(value) <= len(prefix) + 1
    ):
        raise ValueError(f"expected a {prefix}_ identifier")


def require_aware(value: datetime, name: str) -> None:
    """断言时间戳带时区；naive 时间在持久化/回放时会产生跨时区漂移（R03 B-P3）。"""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def require_non_empty(value: str, name: str) -> None:
    """断言字符串非空白；关键 id/正文为空会导致下游配对与检索错乱。"""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")


def validate_json_object(value: Any, name: str) -> None:
    """校验值是映射且可 JSON 化。

    为什么 ``allow_nan=False``：NaN/Inf 能骗过内存构造，但落库/跨语言 wire（JSON）
    会损坏，故在不变式层就拒绝（HARD C2 落盘约束、R03 B-P3）。
    """
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a JSON object")
    try:
        json.dumps(dict(value), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain only JSON-safe values") from exc


def enum_value(value: Enum | str) -> str:
    """把 StrEnum 或字符串统一取其 ``.value``（序列化/比较用）。"""
    return value.value if isinstance(value, Enum) else str(value)


def edit_distance(a: str, b: str) -> int:
    """Levenshtein 距离（纯函数，无 IO）：供工具误名候选提示共用。"""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]
