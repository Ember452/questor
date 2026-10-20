"""L0 提交队列词表：canonical JSON / Command 载荷 / digest / DDL（B3；v3 §4.4）。

耐久提交队列把「用户/审批/取消/模式」意图先落 ``submissions`` 表，再由该 run 的
``RunController`` 在安全点 claim → 交 ``apply``。本模块只放**纯数据与纯函数**：

- ``canonical_json`` / ``command_payload`` / ``command_digest``：同一意图跨进程得到同一指纹，
  **禁止 repr**（repr 绑源码文本，字段顺序/默认值一变就漂移）；
- ``normalize_source``：source 是开放词表（surface 自报，未知记 ``unknown:<raw>`` 不抛）；
- ``kind_for_command``：把 Command 收敛到五类队列 kind；
- ``SUBMISSIONS_DDL``：单一 schema authority 的建表/索引文本，由 store 在 connect 时执行。

本模块不 import state/kernel/providers：L0 只依赖 stdlib 与同层 contracts。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from questor.contracts.common import JsonObject, thaw
from questor.contracts.events import (
    Cancel,
    Command,
    EventType,
    ExpireApproval,
    RecordWarning,
    ResolveApproval,
    SetPermissionMode,
    SubmitMessage,
)

#: digest 语义版本：字段顺序/默认值变化不改摘要；语义变化才 bump。
DIGEST_SCHEMA_VERSION = 1

#: 队列 kind（五类；steer 与 user_message 共用 SubmitMessage，kind 由提交方显式给出）。
SUBMISSION_KINDS: frozenset[str] = frozenset({"user_message", "steer", "approval", "cancel", "mode"})

#: 队列状态：pending → deferred（已 claim 未 ack）→ consumed；discarded 为合法丢弃终态。
SUBMISSION_STATES: frozenset[str] = frozenset({"pending", "deferred", "consumed", "discarded"})

#: 单会话在途（pending+deferred）上限；超出即 QUEUE_FULL，绝不无界增长。
MAX_QUEUE_ITEMS = 512

#: 已知 source 词表；其余按开放词表归一为 ``unknown:<raw>``（不拒收、不抛）。
KNOWN_SOURCES: frozenset[str] = frozenset({"desktop", "http", "openai", "cli", "scheduler"})

SUBMISSIONS_DDL = """
CREATE TABLE IF NOT EXISTS submissions (
    item_id          TEXT    PRIMARY KEY,
    session_id       TEXT    NOT NULL,
    run_id           TEXT,
    seq_in_session   INTEGER NOT NULL,
    kind             TEXT    NOT NULL,
    payload          TEXT    NOT NULL,
    source           TEXT    NOT NULL,
    idem_key         TEXT    NOT NULL,
    digest           TEXT    NOT NULL,
    state            TEXT    NOT NULL,
    change_version   INTEGER NOT NULL,
    created_at       TEXT    NOT NULL,
    UNIQUE (session_id, idem_key)
);
CREATE INDEX IF NOT EXISTS idx_sub_lane ON submissions (session_id, state, seq_in_session);
CREATE INDEX IF NOT EXISTS idx_sub_ver  ON submissions (change_version);
"""


class SubmissionConflictError(ValueError):
    """同一 (session_id, idem_key) 指向了不同 digest：拒绝，绝不后者覆盖前者。"""


class SubmissionQueueFullError(RuntimeError):
    """单会话在途提交达到 ``MAX_QUEUE_ITEMS``：明确背压，不静默丢弃。"""


class CommandDigestConflict(ValueError):
    """命令窗口里同一 ``(run_id, idem_key)`` 指向了不同 digest：拒绝，不覆盖。"""


def _json_default(value: object) -> object:
    """canonical JSON 的叶编码：datetime/Enum/bytes 稳定表示；其余退化为字符串。"""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def canonical_json(value: object) -> str:
    """确定性 JSON：thaw 不可变叶、键排序、紧凑分隔、禁 NaN/Inf。"""
    return json.dumps(
        thaw(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_json_default,
    )


def _encode(value: object, *, identity: bool = False) -> Any:
    """把 Command 及其嵌套 dataclass/冻结容器编码为可 canonical 的普通结构。

    ``identity=True`` 时丢掉 Message 的易变叶（id/seq/created_at）：同一用户原话经重投/
    重建后仍应得到同一 digest（幂等的身份是内容，不是进程内对象元数据）。
    """
    if is_dataclass(value) and not isinstance(value, type):
        encoded: dict[str, Any] = {"__type__": type(value).__name__}
        volatile = {"id", "seq", "created_at"} if identity and type(value).__name__ == "Message" else set()
        for field in fields(value):
            if field.name in volatile:
                continue
            encoded[field.name] = _encode(getattr(value, field.name), identity=identity)
        return encoded
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _encode(v, identity=identity) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_encode(v, identity=identity) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_encode(v, identity=identity) for v in value)
    if hasattr(value, "items"):  # immutables.Map 等只读映射
        return {str(k): _encode(v, identity=identity) for k, v in value.items()}  # type: ignore[union-attr]
    return value


def command_payload(command: Command) -> JsonObject:
    """Command → 可 canonical 的普通 dict（``type`` 判别 + ``fields`` 载荷；含完整元数据）。"""
    return {"type": command.type, "fields": _encode(command)}


def command_identity_payload(command: Command) -> JsonObject:
    """Command 的身份投影：丢弃 Message 的 id/seq/created_at，供 digest 跨重投稳定。"""
    return {"type": command.type, "fields": _encode(command, identity=True)}


def command_digest(command: Command) -> str:
    """命令内容指纹：sha256(canonical_json + "|" + DIGEST_SCHEMA_VERSION)，不用 repr。"""
    raw = canonical_json(command_identity_payload(command))
    return hashlib.sha256(f"{raw}|{DIGEST_SCHEMA_VERSION}".encode()).hexdigest()


def normalize_source(raw: str) -> str:
    """source 开放词表：已知原样，未知 ``unknown:<raw>``（空 → ``unknown:``）。"""
    value = (raw or "").strip()
    if value in KNOWN_SOURCES:
        return value
    return f"unknown:{value}"


def kind_for_command(command: Command) -> str:
    """Command → 五类队列 kind；SubmitMessage 默认 user_message（steer 由提交方显式指定）。"""
    if isinstance(command, SubmitMessage):
        return "user_message"
    if isinstance(command, ResolveApproval | ExpireApproval):
        return "approval"
    if isinstance(command, Cancel):
        return "cancel"
    if isinstance(command, SetPermissionMode):
        return "mode"
    raise ValueError(f"command type {command.type!r} is not a queueable submission")


def is_rejection(command: Command, events: tuple) -> bool:
    """reduce 的拒绝形状：恰好一条 WARNING，且不是合法的 RecordWarning。"""
    return len(events) == 1 and events[0].type == EventType.WARNING and not isinstance(command, RecordWarning)


__all__ = [
    "DIGEST_SCHEMA_VERSION",
    "KNOWN_SOURCES",
    "MAX_QUEUE_ITEMS",
    "SUBMISSIONS_DDL",
    "SUBMISSION_KINDS",
    "SUBMISSION_STATES",
    "SubmissionConflictError",
    "SubmissionQueueFullError",
    "CommandDigestConflict",
    "canonical_json",
    "command_digest",
    "command_identity_payload",
    "command_payload",
    "kind_for_command",
    "is_rejection",
    "normalize_source",
]
