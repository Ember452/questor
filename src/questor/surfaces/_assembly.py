"""组合根共用的**日志装配口径**（L6 surfaces；DESIGN §11）。

为什么单独一个文件：仓库有两个生产入口——``python -m questor``（``__main__``）与
``python -m questor.surfaces.cli``（``cli.main()``）。审计发现后者裸调 ``configure_logging()``，
既不建文件面也无视 ``QUESTOR_LOG_*`` 与 ``QUESTOR_LOG_PAYLOAD`` 门（Issue #138），等于"组合根唯一
装配口径"事实上碎成两半。env 解析收在这里，两个入口共用同一份。

分层归属：env 读取属**组合根/surfaces** 职责，``observability`` 内核保持 env-free（既有
``config ⟂ observability`` independence 契约与 DESIGN §11 的口径）。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from questor.observability.configure import configure_logging, logging_status
from questor.observability.entry import LogLevel

#: 装配完成后的自述行 logger（一方 inline 记录，走桥进主干与 console）。
_LOG = logging.getLogger("questor.assembly")


def console_level_from_env() -> LogLevel:
    """console 级别取自 ``QUESTOR_LOG_LEVEL``（默认 INFO）。"""
    return getattr(LogLevel, os.environ.get("QUESTOR_LOG_LEVEL", "INFO").upper(), LogLevel.INFO)


def log_dir_from_env() -> str:
    """日志目录取自 ``QUESTOR_LOG_DIR``（默认 ``<cwd>/.questor/logs``）。"""
    return os.environ.get("QUESTOR_LOG_DIR", str(Path.cwd() / ".questor" / "logs"))


def keep_days_from_env() -> int:
    """保留天数取自 ``QUESTOR_LOG_KEEP_DAYS``（默认 14）；解析失败回落默认，绝不在装配期崩。"""
    try:
        return int(os.environ.get("QUESTOR_LOG_KEEP_DAYS", "14"))
    except ValueError:
        return 14


def reject_unimplemented_payload() -> None:
    """``QUESTOR_LOG_PAYLOAD`` 解析：preview 截断属刀 3，本期仅解析、拒绝未实现值（T2.14）。

    为什么宁可不启动也不静默忽略：用户设了 ``on`` 就以为日志里有载荷，排障时才发现没有——
    比拒绝启动更坏。
    """
    payload = os.environ.get("QUESTOR_LOG_PAYLOAD", "off").strip().lower()
    if payload not in {"", "off"}:
        raise SystemExit(f"QUESTOR_LOG_PAYLOAD={payload!r} is not implemented yet (preview lands in log blade 3); only 'off' is supported")


def assemble_logging() -> None:
    """按 env 族装配完整管线（带内桥 + console(stderr) + 按日 JSONL 文件面 + errors 分流）。

    装完立刻打一条 ``questor.assembly`` INFO：日志骨架自己"装配好了"这件事也该可观测（DoD A①
    的"起手即有日志"必须由一方记录兑现，不能靠第三方噪声凑数——Issue #126 修完后第三方 DEBUG
    不再进主干，这一点尤其重要）。
    """
    reject_unimplemented_payload()
    console_level = console_level_from_env()
    log_dir = log_dir_from_env()
    keep_days = keep_days_from_env()
    configure_logging(
        console_level=console_level,
        file_level=LogLevel.DEBUG,
        log_dir=log_dir,
        keep_days=keep_days,
        llm_file=False,
    )
    status = logging_status()
    _LOG.info(
        "logging assembled console=%s file=DEBUG log_dir=%s keep_days=%s",
        console_level.name,
        log_dir,
        keep_days,
        extra={"log_fields": {"degraded": bool(status.get("degraded")), "file_level": str(status.get("file_level"))}},
    )
