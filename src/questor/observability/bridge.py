"""L0' 带内桥：stdlib ``logging`` → ``LogEntry``（DESIGN §6；G-L6/G-L12/§16.1）。

三层归属（DESIGN §3）：**内核文件**——运行时 import 只在 observability 包内。

``BridgeHandler`` 装上 root，把每条 ``LogRecord`` 转成 ``LogEntry`` 交 pipeline。两条通道在此
与 ``projection``（带外）汇流到同一个 ``LogEntry``，治理只跑一次。

reality-wins 偏差（记 ADR-0027 §7）：DESIGN §6 的 depth 爬栈是 DeepCode 把记录**重发进 loguru**
才需要的（loguru 需从自身发射点重算 depth）；本 B2 架构直接读已定位的 ``LogRecord.filename/
lineno``——stdlib 在 ``info()`` 调用处经 ``findCaller`` 已把调用点填成业务文件，无需再爬栈（加爬栈
循环反而是 dead code）。G-L6 由 ``record.filename`` 直取即满足。

provenance（hermes MIT）：降噪白名单来自 ``hermes_logging.py:216-227``。§16.1 args 强转为 Questor 自定。
"""

from __future__ import annotations

import logging
import traceback
from datetime import UTC, datetime

from questor.observability.entry import LogEntry, LogLevel
from questor.observability.pipeline import emit as _pipeline_emit
from questor.observability.scope import current_context

#: 带内非标量 arg 强转后 repr 的上界（§16.1）；防单条 repr 撑爆有界性。
_MAX_ARG_REPR = 800
_SCALAR_TYPES: tuple[type, ...] = (str, int, float, bool)

#: 在 DEBUG/INFO 太吵的第三方 logger（钉到 WARNING，否则 litellm/httpx 淹没有用行）。
#: 参照 hermes ``_NOISY_LOGGERS``（MIT）；litellm 单列（其请求日志体量大且与 llm 通道重复）。
NOISY_LOGGERS: tuple[str, ...] = (
    "openai", "openai._base_client", "httpx", "httpcore", "asyncio", "hpack", "hpack.hpack",
    "grpc", "modal", "urllib3", "urllib3.connectionpool", "websockets", "charset_normalizer",
    "markdown_it", "litellm",
)


def quiet_noisy_loggers() -> None:
    """把噪声第三方 logger 钉到 WARNING（装配期由 ``configure`` 调一次）。"""
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def _to_level(levelno: int) -> LogLevel:
    """stdlib 数值级别 → 自有 ``LogLevel``（非标准值就近归档，fail-safe 不抛）。"""
    if levelno >= LogLevel.CRITICAL:
        return LogLevel.CRITICAL
    if levelno >= LogLevel.ERROR:
        return LogLevel.ERROR
    if levelno >= LogLevel.WARNING:
        return LogLevel.WARNING
    if levelno >= LogLevel.INFO:
        return LogLevel.INFO
    return LogLevel.DEBUG


def _coerce_one(value: object) -> tuple[object, bool]:
    """标量原样返回；非标量 → 有界 ``repr`` 字符串并标记被强转（§16.1）。"""
    if value is None or isinstance(value, _SCALAR_TYPES):
        return value, False
    text = repr(value)
    if len(text) > _MAX_ARG_REPR:
        text = text[:_MAX_ARG_REPR] + "…<truncated>"
    return text, True


def _compose_msg(record: logging.LogRecord, is_questor: bool) -> tuple[str, bool]:
    """产出 ``msg``：非 ``questor.*`` 或未带 arg → 直接 ``getMessage()``；否则对 arg 做强转。

    只强转 arg、**不在此脱敏**：脱敏是 pipeline 的唯一单点（D12）。强转把 ``info("run=%s", run)``
    的领域对象压成有界 repr，令 D11 白名单也守住了 ``msg`` 面（§16.1）。
    """
    args = record.args
    if not is_questor or args is None:
        return record.getMessage(), False
    coerced_any = False
    if isinstance(args, dict):
        new_args: object = {}
        for k, v in args.items():
            cv, c = _coerce_one(v)
            new_args[k] = cv  # type: ignore[index]
            coerced_any = coerced_any or c
    elif isinstance(args, tuple):
        items = []
        for v in args:
            cv, c = _coerce_one(v)
            items.append(cv)
            coerced_any = coerced_any or c
        new_args = tuple(items)
    else:
        cv, c = _coerce_one(args)
        new_args = cv
        coerced_any = c
    if not coerced_any:
        return record.getMessage(), False
    try:
        return record.msg % new_args, True
    except Exception:  # noqa: BLE001 - arg 替换失败退回原 msg，绝不因格式化崩日志
        return str(record.msg), True


def _format_traceback(record: logging.LogRecord) -> str | None:
    """由 ``exc_info`` 格式化异常链并**压掉空行**（DESIGN §6；G-L12 落盘单行的前置）。"""
    if not record.exc_info or not any(record.exc_info):
        return None
    raw = "".join(traceback.format_exception(*record.exc_info))
    return "\n".join(line for line in raw.splitlines() if line.strip())


class BridgeHandler(logging.Handler):
    """stdlib Handler：把 ``LogRecord`` 转 ``LogEntry`` 交 pipeline。"""

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102 - 遵循 logging.Handler.emit 契约
        try:
            is_questor = record.name == "questor" or record.name.startswith("questor.")
            msg, coerced = _compose_msg(record, is_questor)
            fields: dict[str, str | int | float | bool | None] = {}
            log_fields = getattr(record, "log_fields", None)
            if isinstance(log_fields, dict):  # 唯一入口：禁把任意 record 属性透传进 fields。
                fields.update(log_fields)
            fields["filename"] = record.filename  # 已是业务调用处（见模块 docstring 偏差说明）。
            fields["lineno"] = record.lineno
            if coerced:
                fields["args_coerced"] = True
            entry = LogEntry(
                ts=datetime.fromtimestamp(record.created, UTC),
                level=_to_level(record.levelno),
                logger=record.name,
                msg=msg,
                fields=fields,
                traceback=_format_traceback(record),
                source="inline",
                context=current_context(),  # 关联键取自 bind() 作用域（G-L5 依赖 loop bind）。
            )
            _pipeline_emit(entry)
        except Exception:  # noqa: BLE001 - 桥自身异常走 stdlib handleError，绝不冒回业务调用方
            self.handleError(record)
