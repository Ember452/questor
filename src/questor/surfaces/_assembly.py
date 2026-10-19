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

from questor.contracts.policy import CompactionConfig
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


#: preview 截断上限（有界，防超大 preview 把 llm 通道撑爆；承 C18/DESIGN §12）。
_PAYLOAD_MAX_CHARS = 8192


def compaction_from_env() -> CompactionConfig | None:
    """``QUESTOR_COMPACTION`` 解析→生产可恢复压缩旋钮（P10/Major-1，ADR-0048）。

    env 读取属**组合根/surfaces** 职责（与 ``QUESTOR_LOG_*`` 同族，内核 env-free）：
    - 未设 / ``off`` → ``None``（**默认不压缩**，向后兼容、不影响既有行为与测试）；
    - ``on`` → 保守默认（以 **context 条数** 为触发信号、非累计花费；保头 2、保尾 6，超 24 条才压）；
    - ``items:N`` → 自定义条数阈值（max_items=N，N>24 才合理但尊重调用方）。
    触发用 ``max_items``（context 体量）而非 ``trigger_tokens``（累计花费）——修正我先前标注的“用错信号”隐患。
    """
    raw = os.environ.get("QUESTOR_COMPACTION", "off").strip().lower()
    if raw in {"", "off"}:
        return None
    if raw == "on":
        return CompactionConfig(keep_head=2, keep_tail=6, max_items=24)
    if raw.startswith("items:"):
        digits = raw[len("items:") :]
        if digits.isdigit() and int(digits) > 0:
            return CompactionConfig(keep_head=2, keep_tail=6, max_items=int(digits))
    # 非法值：宁可不猜也不静默错配——拒绝启动（与 payload 门同口径 fail-closed）。
    raise SystemExit(f"QUESTOR_COMPACTION={raw!r} invalid; use 'off', 'on', or 'items:<N>'")


def payload_preview_from_env() -> int | None:
    """``QUESTOR_LOG_PAYLOAD`` 解析（P10/ADR-0049 刀 3 preview 实装）：

    - ``off``/空 → ``None``（默认零原文，主干与 llm 通道都不落 preview）；
    - ``truncate:N``（1 ≤ N ≤ 8192）→ 截断预算 N（preview 只走独立 llm 通道、必过脱敏）；
    - 其他（含 ``on``、``truncate:0``、``truncate:abc``、越界）→ **拒绝启动**。

    为什么宁可不启动也不静默忽略：用户设了非法值却以为日志里有载荷，排障时才发现没有——
    比拒绝启动更坏（保持与旧 `reject_unimplemented_payload` 同口径的 fail-closed）。"""
    raw = os.environ.get("QUESTOR_LOG_PAYLOAD", "off").strip().lower()
    if raw in {"", "off"}:
        return None
    prefix = "truncate:"
    if not raw.startswith(prefix):
        raise SystemExit(f"QUESTOR_LOG_PAYLOAD={raw!r} invalid; use 'off' or 'truncate:<1..{_PAYLOAD_MAX_CHARS}>'")
    digits = raw[len(prefix) :]
    if not digits.isdigit():
        raise SystemExit(f"QUESTOR_LOG_PAYLOAD={raw!r} invalid; truncate needs an integer")
    n = int(digits)
    if not (1 <= n <= _PAYLOAD_MAX_CHARS):
        raise SystemExit(f"QUESTOR_LOG_PAYLOAD truncate={n} out of range 1..{_PAYLOAD_MAX_CHARS}")
    return n


def assemble_logging() -> None:
    """按 env 族装配完整管线（带内桥 + console(stderr) + 按日 JSONL 文件面 + errors 分流）。

    preview 开启（truncate:N）时自动开独立 ``llm`` 文件通道（``llm_file=True``）；主干恒零原文。
    装完立刻打一条 ``questor.assembly`` INFO（DoD A①"起手即有日志"由一方记录兑现）。
    """
    preview = payload_preview_from_env()
    console_level = console_level_from_env()
    log_dir = log_dir_from_env()
    keep_days = keep_days_from_env()
    configure_logging(
        console_level=console_level,
        file_level=LogLevel.DEBUG,
        log_dir=log_dir,
        keep_days=keep_days,
        llm_file=preview is not None,
    )
    status = logging_status()
    _LOG.info(
        "logging assembled console=%s file=DEBUG log_dir=%s keep_days=%s",
        console_level.name,
        log_dir,
        keep_days,
        extra={"log_fields": {"degraded": bool(status.get("degraded")), "file_level": str(status.get("file_level"))}},
    )
