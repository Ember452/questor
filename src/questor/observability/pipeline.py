"""L0' 治理管线：**脱敏 → 节流 → 来源/级别门 → exporter fan-out**（DESIGN §0/§10/§13）。

三层归属（DESIGN §3）：**内核文件**——运行时 import 只在 ``questor.observability`` 包内
（``entry``/``exporter``/``redact``），绝不引用 observability 之外的业务层（这是"可抽包"的真
红线；G-L1 语义 = 禁跨包，不是禁兄弟）。治理逻辑在此**只实现一次**，覆盖带内桥与带外投影两条通道。

四条治理纪律（缺陷审计后补齐，见 Issue #126/#128/#131/#132）：
- **来源门（准入边界）**：logger 名不是 ``questor``/``questor.*`` 的记录视为"外来"，其有效
  ``min_level`` 恒 ≥ INFO——**不受 ``file_level=DEBUG`` 放宽**。为什么：第三方库（aiosqlite 会打印
  SQL + 完整参数元组、litellm 打印请求体）的 DEBUG 一旦进主干文件，DESIGN D4 的"零原文默认"就
  被旁路击穿，且日志沦为账本的第二份副本（HARD C13）。逐个库打名单永远追不上，默认拒绝才可扩展。
- **错误不节流**：ERROR/CRITICAL 完全绕过节流窗（HARD C6 错误绝不静默）。
- **形状指纹**：节流签名用归一后的 msg 形状（数字/十六进制/引号串 → ``<*>``）+ 关联 ``run_id``，
  既不因"仅数字不同"漏合并（风暴无抑制），也不因"msg 相同、实体不同"过合并（吞掉别的 run 的错误）。
- **绝不上冒**：管线自身异常也兜住（计数 + 丢弃），不只是 exporter 调用那一段——带外投影的调用点在
  surfaces 消费者的 await 循环里，抛出即打穿宿主面（D13/C10 对称面）。

级别过滤在 fan-out 处按 **每个 sink 自己的 ``min_level``** 读（console=INFO / errors=WARNING /
主干文件=可变态 file_level）：故 §16.3 降级只把主干 sink 的 ``min_level`` 抬到 INFO，``errors`` lane
不受影响（它本就是 WARNING+，DESIGN §10）。exporter 无 ``min_level`` 属性时默认收 DEBUG+。
"""

from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from questor.observability.entry import LogLevel
from questor.observability.exporter import current_exporters
from questor.observability.redact import redact

if TYPE_CHECKING:  # 仅类型。
    from questor.observability.entry import LogEntry

#: 节流窗口（DESIGN §13，默认 1s）。
_WINDOW_SECONDS = 1.0
#: 无 ``min_level`` 属性的 exporter 默认收下界（一方记录适用；外来记录另加来源门）。
_DEFAULT_MIN_LEVEL = LogLevel.DEBUG
#: 一方 logger 根名——只有它及 ``questor.*`` 子名算"自有记录"（准入边界）。
_FIRST_PARTY_ROOT = "questor"
#: 外来记录的有效级别下界（默认拒绝 DEBUG，见模块 docstring）。
_THIRD_PARTY_FLOOR = LogLevel.INFO
#: 完全绕过节流的级别（C6：错误绝不静默）。
_UNTHROTTLED_FLOOR = LogLevel.ERROR
#: 形状归一上限：指纹只用于比较，绝不因此放大内存。
_SHAPE_MAX = 200
#: 形状归一模式（顺序应用）：十六进制串、数字、单/双引号串 → ``<*>``。
_SHAPE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"0x[0-9a-fA-F]+"),
    re.compile(r"\d+"),
    re.compile(r"'[^']*'"),
    re.compile(r'"[^"]*"'),
)


def _is_first_party(logger: str) -> bool:
    """logger 名是否属于 questor 自有（``questor`` 本体或 ``questor.`` 前缀）。"""
    return logger == _FIRST_PARTY_ROOT or logger.startswith(f"{_FIRST_PARTY_ROOT}.")


def _shape(msg: str) -> str:
    """把 msg 归一成"形状"：可变的具体值抹平成 ``<*>``，只留结构。

    为什么不是完整 msg（Issue #131）：真实日志风暴的形态是"同一代码行、值不同"，用完整 msg 当
    指纹等于零抑制；而反过来用完整 msg 又会把"同一形状、不同实体"的行判成重复。
    """
    out = msg
    for pattern in _SHAPE_PATTERNS:
        out = pattern.sub("<*>", out)
    return out[:_SHAPE_MAX]


@dataclass
class _Window:
    """一个 (logger, level, 形状, run_id) 签名的当前节流窗：记录开窗时刻、被抑制计数、代表 entry。"""

    start: float
    suppressed: int
    entry: LogEntry


#: 节流签名四元组：见 ``_sig``。
_Signature = tuple[str, LogLevel, str, str | int | float | bool | None]
_throttle: dict[_Signature, _Window] = {}
_disabled: list[object] = []
_dropped_records = 0


def _sig(entry: LogEntry) -> _Signature:
    """节流签名 =（logger, level, msg 形状, 关联 run_id）。

    ``run_id`` 进签名是"跨 run 永不合并"的关键（Issue #128）：两个 run 同秒失败必须各留一行，
    否则后一个 run 的 ERROR 在日志里彻底消失。无关联键的记录退回 ``None`` 分组，仍受形状归一约束。
    """
    return (entry.logger, entry.level, _shape(entry.msg), entry.context.get("run_id"))


def _clock() -> float:
    """单调时钟源；测试 monkeypatch 本函数注入确定时间（避免 sleep 依赖）。"""
    return time.monotonic()


def reset() -> None:
    """清空管线态（节流窗 / 禁用集 / 丢弃计数）。装配 ``force=True`` 重配与测试隔离调用。"""
    global _dropped_records
    _throttle.clear()
    _disabled.clear()
    _dropped_records = 0


def stats() -> dict:
    """自我观测读数（DESIGN §13）：被禁用的 exporter 名单 + 累计丢弃记录数（供 ``logging_status`` 取）。"""
    return {
        "dropped_records": _dropped_records,
        "disabled_exporters": [getattr(e, "name", type(e).__name__) for e in _disabled],
    }


def _is_disabled(exp: object) -> bool:
    return any(exp is d for d in _disabled)


def emit(entry: LogEntry) -> None:
    """管线唯一入口：脱敏 → 节流 → fan-out。**绝不上冒**（含管线自身异常，Issue #132）。

    为什么顶层也要 try：带外投影 ``log_envelope`` 由 surfaces 的消费者在 await 循环里裸调，桥虽然
    包了 try，但 ``redact`` 的 fail-closed 重建、节流窗尾补行都可能触发 ``LogEntry`` 不变式而抛出——
    观测面绝不能把被观测物带崩（D13/C10 对称面）。
    """
    global _dropped_records
    try:
        _emit_guarded(entry)
    except Exception:  # noqa: BLE001 - 管线自身故障按丢弃计数，绝不冒回调用方
        _dropped_records += 1


def _emit_guarded(entry: LogEntry) -> None:
    entry = redact(entry)  # 全系统唯一脱敏点（D12）；redact 自身 fail-closed。
    now = _clock()
    _flush_due(now)
    if entry.level >= _UNTHROTTLED_FLOOR:  # C6：错误类永不进节流窗，也就永不会被合并吞掉
        _fanout(entry)
        return
    sig = _sig(entry)
    win = _throttle.get(sig)
    if win is None:
        # 首次立即放行（响应性优先），并开窗计抑制数。
        _throttle[sig] = _Window(start=now, suppressed=0, entry=entry)
        _fanout(entry)
    elif now - win.start <= _WINDOW_SECONDS:
        win.suppressed += 1
    else:  # 防御：正常由 _flush_due 关窗；这里兜住时钟回拨/竞态后重开。
        win.start = now
        win.suppressed = 0
        win.entry = entry
        _fanout(entry)


def flush() -> None:
    """关闭所有节流窗、补发窗尾 ``repeated N times``（teardown/atexit/测试末尾刷新用）。

    逐窗兜异常：一个坏窗不该让其余窗的补行一起丢掉（Issue #132/#136）。
    """
    global _dropped_records
    for sig in list(_throttle):
        try:
            _close(sig, _throttle[sig])
        except Exception:  # noqa: BLE001 - 观测面不上冒；该窗按丢弃计
            _throttle.pop(sig, None)
            _dropped_records += 1


def _flush_due(now: float) -> None:
    for sig in list(_throttle):
        if now - _throttle[sig].start > _WINDOW_SECONDS:
            _close(sig, _throttle[sig])


def _close(sig: tuple, win: _Window) -> None:
    _throttle.pop(sig, None)
    if win.suppressed > 0:
        # 窗尾补一条代表记录，携 fields["repeated"]=被抑制条数；各 sink 渲染成 "repeated N times"。
        _fanout(replace(win.entry, fields=_without_context_keys(win.entry, {"repeated": win.suppressed})))


def _without_context_keys(entry: LogEntry, extra: dict[str, str | int | float | bool | None]) -> dict:
    """把待注入的标记键与 ``context`` 去撞（不变式 5 禁同键，撞了就弃标记键保整行）。

    为什么不能直接 ``{**fields, key: value}``：一旦 ``context`` 里已有同名键，``dataclasses.replace``
    会重跑 ``__post_init__`` 并抛 ``ValueError``——节流补行这种事绝不该反过来把日志弄没。
    """
    fields = {**entry.fields, **extra}
    return {k: v for k, v in fields.items() if k not in entry.context}


def _effective_min(exp: object, entry: LogEntry) -> LogLevel:
    """该 sink 对**这条记录**的级别下界：外来记录额外抬到 INFO（准入边界，Issue #126）。"""
    base = getattr(exp, "min_level", _DEFAULT_MIN_LEVEL)
    if _is_first_party(entry.logger):
        return base
    return max(base, _THIRD_PARTY_FLOOR)


def _fanout(entry: LogEntry) -> None:
    global _dropped_records
    for exp in current_exporters():
        if _is_disabled(exp):
            _dropped_records += 1
            continue
        if entry.level < _effective_min(exp, entry):
            continue
        try:
            exp.emit(entry)
        except Exception as exc:  # noqa: BLE001 - D13：一个 sink 崩（磁盘满/文件锁）绝不带崩主循环
            _disabled.append(exp)
            _dropped_records += 1
            _warn_disable(exp, exc)


def _warn_disable(exp: object, exc: BaseException) -> None:
    name = getattr(exp, "name", type(exp).__name__)
    try:  # 直写 stderr（不进 logging，防自触发递归）；写失败也吞——观测面绝不拖垮被观测物。
        sys.stderr.write(f"questor.observability: exporter '{name}' disabled after error: {exc!r}\n")
        sys.stderr.flush()
    except Exception:  # noqa: BLE001
        pass
