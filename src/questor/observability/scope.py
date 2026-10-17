"""L0' 关联作用域：``bind()`` / ``current_context()``（contextvars，task 作用域）。

三层归属（DESIGN §3/§5）：**内核文件**，零 ``questor.*`` 依赖，只 import stdlib。

为什么用 ``contextvars`` 而非 ``threading.local``（D6）：``http_sse`` 一进程并发多个 run
（多个 asyncio task），``threading.local`` 会让各 run 的关联字段互相串号；``contextvars``
在 ``asyncio.create_task`` 处按 task 复制上下文，天然隔离。

为什么是"加键语义"而非 ``bind(run_id, turn)`` 固定槽（DESIGN §5.1）：P8 子 agent 要
``parent_run_id``、P10 tracing 要 ``trace_id``——固定槽意味着改**已发布签名**（破坏性变更），
加键语义下这些都只是新增一个键。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

#: 允许值类型与 ``entry.LogEntry`` 白名单一致（D11）；``bool`` 是 ``int`` 子类，一并覆盖。
_ALLOWED_VALUE_TYPES: tuple[type, ...] = (str, int, float, bool)

# 存的是"当前快照 dict"：bind 从不就地改这个 dict，而是合并出**新** dict 再 set，故默认共享安全
# （退出靠 token reset，不靠清空可变对象）。用 ``None`` 而非可变 ``{}`` 作默认：ruff 禁 ContextVar
# 可变默认，且 ``None`` 明确区分"未绑定"与"绑成空"。
_SCOPE: ContextVar[dict[str, str | int | float | bool | None] | None] = ContextVar("questor_log_context", default=None)


def _current() -> dict[str, str | int | float | bool | None]:
    """取当前快照；未绑定归一为空 dict（调用方永远拿到 dict，不必各自判 None）。"""
    snap = _SCOPE.get()
    return snap if snap is not None else {}


def _validate_binding(kv: dict[str, object]) -> None:
    """校验绑定键值：键 ``str``、值白名单标量或 ``None``，非白名单当场 ``TypeError``。

    与 ``LogEntry`` 同源纪律：关联键也绝不许塞领域对象（否则 ``bind(run=run)`` 绕过 D11）。
    """
    for key, value in kv.items():
        if not isinstance(key, str):
            raise TypeError(f"bind keys must be str, got {type(key).__name__}")
        if value is not None and not isinstance(value, _ALLOWED_VALUE_TYPES):
            raise TypeError(f"bind[{key!r}] must be str/int/float/bool/None, got {type(value).__name__}")


@contextmanager
def bind(**kv: str | int | float | bool | None) -> Iterator[dict[str, str | int | float | bool | None]]:
    """在当前 task 上下文叠加关联键；退出还原到进入前。

    加键 + 同键重盖章语义：新键合并进来；同名键以本次 ``kv`` 覆盖（loop 每轮 ``bind(turn=…)``
    正是靠同名覆盖从权威 ``turn`` 重盖章，号不漂移，D5）。yield 出合并后的快照。
    """
    _validate_binding(kv)
    merged = {**_current(), **kv}
    token = _SCOPE.set(merged)
    try:
        yield merged
    finally:
        _SCOPE.reset(token)


def current_context() -> dict[str, str | int | float | bool | None]:
    """返回当前关联快照的**副本**（外部改写不得污染作用域）。"""
    return dict(_current())
