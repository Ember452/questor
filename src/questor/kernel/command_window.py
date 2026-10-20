"""L2 有界命令窗口策略：canonical digest + 有界载荷 + 拒绝形状（B2；v3 §4.3）。

窗口是**优化层**，不是真相：只记录被 ``apply`` 接受的命令，供同流长前缀 A/B 与
任意 cseq 前缀 time-travel。字段/默认值变化不改摘要（canonical JSON + schema version），
**禁用 repr**（repr 绑源码文本）。裁窗规则见 c3：只清被 ``last_consolidated`` 吸收的段，
保留最近 ``WINDOW_MIN_ROWS``，全局超 ``MAX_WINDOW_ROWS`` 按最旧 run 整批 drop。
"""

from __future__ import annotations

from questor.contracts.events import Command
from questor.contracts.submissions import (
    DIGEST_SCHEMA_VERSION,
    canonical_json,
    command_digest,
    command_payload,
    is_rejection,
)

#: 每 run 保留的最近窗口行（即使已被巩固吸收，供当场 A/B）。
WINDOW_MIN_ROWS = 512

#: 全局上限；超限按最旧 run 整批 drop + maintenance 告警。
MAX_WINDOW_ROWS = 20_000

#: 单条 payload 上限；超限只存有界 placeholder（digest 仍按全量算，身份不丢）。
MAX_PAYLOAD_BYTES = 64 * 1024


def window_payload(command: Command) -> str:
    """命令窗口里的有界 canonical payload；超限存 ``{truncated, bytes, preview}``。"""
    raw = canonical_json(command_payload(command))
    encoded = raw.encode("utf-8")
    if len(encoded) <= MAX_PAYLOAD_BYTES:
        return raw
    return canonical_json({"truncated": True, "bytes": len(encoded), "preview": raw[:MAX_PAYLOAD_BYTES]})


def trim_plan(rows: list[dict], last_consolidated: int, *, min_rows: int = WINDOW_MIN_ROWS) -> list[int]:
    """只清被 ``last_consolidated`` 吸收的段，且保留最近 ``min_rows`` 行；返回待删 cseq。"""
    absorbed = [row for row in rows if int(row["seq"]) <= last_consolidated]
    keep = {row["cseq"] for row in absorbed[-max(0, min_rows) :]}
    return [row["cseq"] for row in absorbed if row["cseq"] not in keep]


def global_trim_plan(rows: list[dict], *, max_rows: int = MAX_WINDOW_ROWS) -> list[int]:
    """全局超限时按最旧 run 整批 drop；返回待删 cseq（绝不拆到半 run）。"""
    if len(rows) <= max_rows:
        return []
    by_run: dict[str, list[int]] = {}
    first_seen: dict[str, int] = {}
    for row in rows:
        run_id = str(row["run_id"])
        by_run.setdefault(run_id, []).append(int(row["cseq"]))
        first_seen.setdefault(run_id, int(row["cseq"]))
    deleted: list[int] = []
    remaining = len(rows)
    for run_id in sorted(by_run, key=lambda rid: first_seen[rid]):
        deleted.extend(by_run[run_id])
        remaining -= len(by_run[run_id])
        if remaining <= max_rows:
            break
    return deleted


__all__ = [
    "DIGEST_SCHEMA_VERSION",
    "MAX_PAYLOAD_BYTES",
    "MAX_WINDOW_ROWS",
    "WINDOW_MIN_ROWS",
    "command_digest",
    "global_trim_plan",
    "is_rejection",
    "trim_plan",
    "window_payload",
]
