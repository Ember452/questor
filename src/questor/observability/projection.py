"""L1 适配层投影：``Envelope`` → ``LogEntry``（DESIGN §7/§9；G-L11；C5/C6）。

**唯一允许 ``import questor.contracts`` 的文件**——抽包时它**留在 questor**（九内核文件不认得
Envelope，只认得 ``LogEntry``；本文件把两者接起来）。带外投影是**只读旁路订阅**：不改 bus 持久化
路径、不新增 Command/事件 type（C5，协议 schema 零 diff）。

三条纪律：
- 级别映射（C6 错误类绝不静默）：``run_failed``→ERROR；``warning``/``resync_required``→WARNING；
  里程碑（``run_started``/``run_completed``/``run_cancelled``）→INFO；余→DEBUG。
- live-only 热路径直接丢弃（体量无界/风暴源，与 design/01 I3 同源）：补齐 ``usage_delta``/
  ``node_updated``（旧 ``log_event`` 缺这两条）。
- 载荷**只取静态白名单键**（G-L11）：绝不做全量 ``json.dumps(env.data)``（那等于把 prompt 与工具
  结果整包抄进日志文件）。所有对 ``env.data`` 的读取都经由下面的常量，AST 守卫据此核对白名单。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from questor.contracts.events import EventType
from questor.observability.entry import LogEntry, LogLevel
from questor.observability.pipeline import emit as _pipeline_emit

if TYPE_CHECKING:  # 仅类型（Envelope 运行时由调用方传入，不在此 import）。
    from questor.contracts.events import Envelope

#: live-only 事件：永不进日志（丢弃比节流更省，且它们无排障信息量，DESIGN §7）。
LIVE_ONLY_TYPES: frozenset[str] = frozenset(
    {
        EventType.TEXT_DELTA,
        EventType.REASONING_DELTA,
        EventType.TOOL_PROGRESS,
        EventType.HEARTBEAT,
        EventType.USAGE_DELTA,
        EventType.NODE_UPDATED,
    }
)

#: 事件类型 → 日志级别（错误类非静默 C6；里程碑 INFO；缺省 DEBUG）。
_LEVEL_MAP: dict[str, LogLevel] = {
    EventType.RUN_FAILED: LogLevel.ERROR,
    EventType.WARNING: LogLevel.WARNING,
    EventType.RESYNC_REQUIRED: LogLevel.WARNING,
    EventType.RUN_STARTED: LogLevel.INFO,
    EventType.RUN_COMPLETED: LogLevel.INFO,
    EventType.RUN_CANCELLED: LogLevel.INFO,
}

#: G-L11 静态载荷白名单——只这些标量键允许进日志（prompt/result/arguments/tool 输出等一律不进）。
#: ``message``/``reason``/``expected``/``current`` 是为错误类事件补的（Issue #137）：
#: ``warning`` 的全部载荷就是 ``message``，``resync_required`` 就是 ``reason``/``expected``/``current``——
#: 不收它们则日志行只剩 "event warning"，级别对、内容空，排障时“知道出事了但不知道出了什么事”。
#: 这些值全部由内核自己写入且已过 ``isinstance`` 标量，扩大的名单由 scripts/check_projection_whitelist.py 机器守。
_DATA_KEYS: tuple[str, ...] = (
    "status",
    "exit_reason",
    "name",
    "tool_use_id",
    "gseq",
    "message",
    "reason",
    "expected",
    "current",
)
#: ``data["error"]`` 容器下允许的子键（归一化错误的 code/message）。
_ERROR_CONTAINER_KEY = "error"
_ERROR_SUB_KEYS: tuple[str, ...] = ("code", "message")


def _project_payload(env: Envelope) -> dict[str, str | int | float | bool | None]:
    """从 ``env.data`` 只提取白名单键（值必须标量）；其余（含 prompt/result）一律丢弃。"""
    data = env.data
    fields: dict[str, str | int | float | bool | None] = {"seq": env.seq}
    for key in _DATA_KEYS:
        if key in data and isinstance(data[key], (str, int, float, bool)):
            fields[key] = data[key]
    err = data.get(_ERROR_CONTAINER_KEY)
    if isinstance(err, Mapping):
        for sub in _ERROR_SUB_KEYS:
            if sub in err and isinstance(err[sub], str):
                fields[f"error_{sub}"] = err[sub]
    return fields


def project(env: Envelope) -> LogEntry | None:
    """把一条 ``Envelope`` 投成 ``LogEntry``；live-only 返回 ``None``（丢弃）。

    ``source="event"``（带外），关联键 ``run_id``/``turn`` 直接取自信封（不依赖 ``bind`` 作用域——
    这是 B① "带外行同 run_id" 的来源）；``seq`` 由 ``Envelope.seq`` 带（带内不知 seq，DESIGN §5.5）。
    """
    if env.type in LIVE_ONLY_TYPES:
        return None
    context: dict[str, str | int | float | bool | None] = {"run_id": env.run_id}
    if env.turn is not None:
        context["turn"] = env.turn
    return LogEntry(
        ts=env.ts,
        level=_LEVEL_MAP.get(env.type, LogLevel.DEBUG),
        logger=f"questor.events.{env.type}",
        msg=f"event {env.type}",
        fields=_project_payload(env),
        traceback=None,
        source="event",
        context=context,
    )


def log_envelope(env: Envelope) -> None:
    """投影并汇入 pipeline（迁移自旧 ``log_event``；调用点在 surfaces 的事件消费处）。"""
    entry = project(env)
    if entry is not None:
        _pipeline_emit(entry)
