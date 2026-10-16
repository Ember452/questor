"""L0' 治理管线：**脱敏 → 节流 → 级别 → exporter fan-out**（DESIGN §0/§10/§13）。

三层归属（DESIGN §3）：**内核文件**——运行时 import 只在 ``questor.observability`` 包内
（``entry``/``exporter``/``redact``），绝不引用 observability 之外的业务层（这是"可抽包"的真
红线；G-L1 语义 = 禁跨包，不是禁兄弟）。治理逻辑在此**只实现一次**，覆盖带内桥与带外投影两条通道。

级别过滤在 fan-out 处按 **每个 sink 自己的 ``min_level``** 读（console=INFO / errors=WARNING /
主干文件=可变态 file_level）：故 §16.3 降级只把主干 sink 的 ``min_level`` 抬到 INFO，``errors`` lane
不受影响（它本就是 WARNING+，DESIGN §10）。exporter 无 ``min_level`` 属性时默认收 DEBUG+。
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from questor.observability.entry import LogLevel
from questor.observability.exporter import current_exporters
from questor.observability.redact import redact

if TYPE_CHECKING:  # 仅类型。
    from questor.observability.entry import LogEntry

#: 节流窗口（DESIGN §13，默认 1s）。v1 指纹用完整 msg（相同行才合并；形状归一是将来细化点）。
_WINDOW_SECONDS = 1.0
_DEFAULT_MIN_LEVEL = LogLevel.DEBUG


@dataclass
class _Window:
    """一个 (logger, level, msg) 签名的当前节流窗：记录开窗时刻、被抑制计数、代表 entry。"""

    start: float
    suppressed: int
    entry: LogEntry


_throttle: dict[tuple[str, LogLevel, str], _Window] = {}
_disabled: list[object] = []
_dropped_records = 0


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
    """管线唯一入口：脱敏 → 节流 → fan-out。绝不上冒（自身异常吞、exporter 异常禁用）。"""
    entry = redact(entry)  # 全系统唯一脱敏点（D12）；redact 自身 fail-closed。
    now = _clock()
    _flush_due(now)
    sig = (entry.logger, entry.level, entry.msg)
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
    """关闭所有节流窗、补发窗尾 ``repeated N times``（teardown/测试/末尾刷新用）。"""
    for sig in list(_throttle):
        _close(sig, _throttle[sig])


def _flush_due(now: float) -> None:
    for sig in list(_throttle):
        if now - _throttle[sig].start > _WINDOW_SECONDS:
            _close(sig, _throttle[sig])


def _close(sig: tuple, win: _Window) -> None:
    _throttle.pop(sig, None)
    if win.suppressed > 0:
        # 窗尾补一条代表记录，携 fields["repeated"]=被抑制条数；各 sink 渲染成 "repeated N times"。
        summary = replace(win.entry, fields={**win.entry.fields, "repeated": win.suppressed})
        _fanout(summary)


def _fanout(entry: LogEntry) -> None:
    global _dropped_records
    for exp in current_exporters():
        if _is_disabled(exp):
            _dropped_records += 1
            continue
        min_level = getattr(exp, "min_level", _DEFAULT_MIN_LEVEL)
        if entry.level < min_level:
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
