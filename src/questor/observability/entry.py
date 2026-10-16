"""L0' 可观测性内核契约：``LogEntry`` 中间表示 + ``LogLevel`` 枚举 + fields 白名单值域。

三层归属（DESIGN §3）：这是**内核文件**——零 ``questor.*`` 依赖（连 ``contracts`` 都不许），
只 import stdlib。这是"将来抽包 = 纯机械搬目录"的前提（ADR-0027；机械守由 G-L1/G-L2 的
``scripts/check_log_kernel_isolation.py`` + ``.importlinter`` 第五契约意图声明）。

刻意的不变式（DESIGN §4，全部 fail-closed）：白名单把"日志不得携带 questor 领域对象"从
文档纪律变成运行时 ``TypeError``——第一个 ``fields={"run": run}`` 的人在本地测试当场炸。
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

#: msg 有界上限（DESIGN §4 / HARD C18）：超限截断，禁止无限长行污染 JSONL 的单行约束。
MAX_MSG_CHARS = 8 * 1024  # 8 KiB

#: ``fields`` / ``context`` 允许的值类型（D11 白名单）。``bool`` 是 ``int`` 子类，一并覆盖。
_ALLOWED_VALUE_TYPES: tuple[type, ...] = (str, int, float, bool)

#: 通道来源二值（DESIGN §4）：``inline``=带内桥产物；``event``=带外投影产物。
_SOURCES: frozenset[str] = frozenset({"inline", "event"})


class LogLevel(enum.IntEnum):
    """自有级别枚举，取值对齐 stdlib ``logging`` 数值以支持跨面比较与 pipeline 过滤。

    用 ``IntEnum`` 而非到处传 ``logging`` 常量：级别语义在此是自有的，各 exporter 各自渲染；
    数值序保证 ``DEBUG < INFO < WARNING < ERROR < CRITICAL`` 可直接 ``>=`` 比较。
    """

    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50


def _validate_mapping(name: str, mapping: dict[str, Any]) -> None:
    """校验 ``fields``/``context`` 的键值域：键必须 ``str``，值必须白名单标量或 ``None``。

    为什么严格：值域放宽成 ``object`` 会让"不许把 ``Run``/``Envelope`` 塞进日志"只能靠 ADR
    自律与 review 人眼（DESIGN D11）。非白名单当场 ``TypeError``——**不是**静默 ``str()`` 转换。
    """
    for key, value in mapping.items():
        if not isinstance(key, str):
            raise TypeError(f"LogEntry.{name} keys must be str, got {type(key).__name__}")
        if value is None:
            continue
        if not isinstance(value, _ALLOWED_VALUE_TYPES):
            raise TypeError(
                f"LogEntry.{name}[{key!r}] must be str/int/float/bool/None, got "
                f"{type(value).__name__} (whitelist D11: never a domain object)"
            )


@dataclass(frozen=True)
class LogEntry:
    """一条归一化日志记录——带内桥与带外投影在此唯一汇流，治理逻辑只实现一次（DESIGN §0）。

    字段语义（DESIGN §4）：``ts`` 强制 tz-aware；``level`` 自有枚举；``logger`` 点分名；
    ``msg`` 已格式化文本（绝不含未展开 ``%s``）；``fields``/``context`` 白名单标量；
    ``traceback`` 保留完整栈（落盘时压空行）；``source`` 标通道来源；``msg_truncated`` 由
    ``__post_init__`` 在 msg 超 ``MAX_MSG_CHARS`` 时置真。构造即校验，全 fail-closed。
    """

    ts: datetime
    level: LogLevel
    logger: str
    msg: str
    fields: dict[str, str | int | float | bool | None] = field(default_factory=dict)
    traceback: str | None = None
    source: Literal["inline", "event"] = "inline"
    context: dict[str, str | int | float | bool | None] = field(default_factory=dict)
    msg_truncated: bool = False

    def __post_init__(self) -> None:
        # 不变式 1：naive datetime → ValueError（跨时区持久化/回放漂移，R03 B-P3）。自实现，
        # 不 import contracts.common.require_aware——内核必须零 questor 依赖（G-L1）。
        if self.ts.tzinfo is None or self.ts.utcoffset() is None:
            raise ValueError("LogEntry.ts must be timezone-aware (naive timestamps drift across TZ)")

        # 不变式 2：fields/context 值域白名单（非白名单 → TypeError，绝不静默 str()）。
        _validate_mapping("fields", self.fields)
        _validate_mapping("context", self.context)

        # 不变式 5：context ∩ fields 同键 → ValueError（禁止静默覆盖或靠合并顺序定义语义）。
        overlap = set(self.fields) & set(self.context)
        if overlap:
            raise ValueError(f"LogEntry context/fields share key(s) {sorted(overlap)}; keys must be disjoint")

        # 不变式 4：source 只允许 inline/event 二值。
        if self.source not in _SOURCES:
            raise ValueError(f"LogEntry.source must be one of {sorted(_SOURCES)}, got {self.source!r}")

        # 不变式 3：msg 有界——超 MAX_MSG_CHARS 截断 + msg_truncated=True（frozen → object.__setattr__）。
        if len(self.msg) > MAX_MSG_CHARS:
            object.__setattr__(self, "msg", self.msg[:MAX_MSG_CHARS])
            object.__setattr__(self, "msg_truncated", True)
