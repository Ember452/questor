"""L4 记忆写回八纪律（B9；v3 §6.4，全部来自审查 §4.2 的接受项）。

八条纪律在本模块里都有**可调用的落点**（不是注释）：

1. **配额闸**：剩余配额低于 ``MIN_RATE_LIMIT_REMAINING_PERCENT`` 就不开工——夜间批
   不得吃光用户推理配额（实际用量由调用方注入的可调用对象提供，None = 未知 → 保守不开工?
   不：未知视为不启用该闸，保持现路径可用）。
2. **抽取输入预算**：``MAX_EXTRACT_BYTES`` / ``MAX_RECORD_BYTES`` 双上限，**保留最新并恢复源序**，
   并在正文里明写"这不是完整历史、不得用作 resume 输入"。
3. **入站脱敏**：写记忆前过 `observability.redact.redact_secrets`（与日志主干同一组规则）。
4. **媒体占位符**：图片/附件正文降级成占位描述，绝不把 base64 塞进记忆。
5. **归因位**：每条记忆标 ``attributed_to: user|assistant``（用户声明优先于模型推断）。
6. **软删位 + 删除事件**：撤回不建 ``memory_history`` 表（§20 C-7），史从事件流投影。
7. **硬过期**：``expires_at`` 与时间衰减**分离**——衰减只排序，过期才退出检索。
8. **代际平行根**：``memory_store/`` 与 ``memory_store_v2/`` 共存，回滚粒度是整根；
   **拒绝符号链接根**（符号链接会让"回滚一根"变成"改写别处"）。

本模块**纯函数为主**（除 `generation_root` 的符号链接判定需 stat），便于逐条单测。
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from types import MappingProxyType

from questor.contracts.common import require_non_empty, utc_now
from questor.contracts.memory import MemoryScope, MemoryWrite, MemoryWriteKind
from questor.observability.redact import redact_secrets

#: 纪律①：剩余配额低于此百分比就不开巩固/蒸馏批。
MIN_RATE_LIMIT_REMAINING_PERCENT = 10

#: 纪律②：一次抽取输入的字节上限（codex `rollout_input.rs` 同量级）。
MAX_EXTRACT_BYTES = 8 * 1024 * 1024

#: 纪律②：单条记录的字节上限。
MAX_RECORD_BYTES = 1024 * 1024

#: 纪律②：明写"这不是完整历史"（防被当重放输入）。
NOT_A_COMPLETE_HISTORY = "[bounded extract: this is NOT a complete history and must never be used as resume input]"

#: 纪律④：媒体降级占位符。
MEDIA_PLACEHOLDER = "[media omitted: image/attachment reference kept, bytes dropped]"

_MEDIA_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=\s]+"),
    re.compile(r"<(img|attachment|audio|video)\b[^>]*/?>", re.IGNORECASE),
    re.compile(r"!\[[^\]]*\]\([^)]*\)"),  # markdown 图片
)

#: 纪律⑧：代际平行根的名字规则（v1 = 基名，vN = `<base>_vN`）。
GENERATION_ROOT_SUFFIX = "_v"

#: 分层保留期（天）；core 常绿无 TTL。None = 永不过期。
TIER_RETENTION_DAYS: MappingProxyType[str, int | None] = MappingProxyType(
    {
        "core": None,
        "daily": 180,
        "sessions": 90,
        "dreams": 14,
    }
)


def quota_allows(remaining_percent: int | float | None, *, min_remaining: int = MIN_RATE_LIMIT_REMAINING_PERCENT) -> bool:
    """纪律①：配额闸。``None`` = 没有配额来源（不启用该闸，保持现路径可用）。"""
    if remaining_percent is None:
        return True
    return float(remaining_percent) >= min_remaining


def retention_expiry(tier: str, *, now: datetime | None = None) -> datetime | None:
    """纪律⑦：按层算硬过期时刻（core 等未登记层 = 永不过期）。"""
    days = TIER_RETENTION_DAYS.get(tier)
    if days is None:
        return None
    return (now or utc_now()) + timedelta(days=days)


def redact_inbound(text: str) -> str:
    """纪律③：入站脱敏（与日志主干共用 `redact_secrets`，不另造一套规则）。"""
    return redact_secrets(text)


def media_placeholder(text: str) -> str:
    """纪律④：媒体正文降级为占位描述（codex 注释原话的做法）。"""
    out = text
    for pattern in _MEDIA_PATTERNS:
        out = pattern.sub(MEDIA_PLACEHOLDER, out)
    return out


def bounded_extract(items: Sequence[str], *, budget_bytes: int = MAX_EXTRACT_BYTES) -> tuple[str, int]:
    """纪律②：按字节预算**保留最新**若干条，再按源序输出；返回 (正文, 丢弃条数)。

    为什么"保留最新、按源序输出"：只按预算截尾会丢掉最有价值的近期事实，而倒序输出
    会让模型把时间线读反。两者分开处理才对。
    """
    if budget_bytes <= 0:
        return "", len(items)
    kept: list[str] = []
    used = 0
    for text in reversed(list(items)):
        size = len(text.encode("utf-8"))
        if kept and used + size > budget_bytes:
            break
        kept.append(text)
        used += size
    dropped = len(items) - len(kept)
    ordered = list(reversed(kept))
    body = "\n".join(ordered)
    if dropped:
        body = f"{body}\n{NOT_A_COMPLETE_HISTORY}".strip()
    return body, dropped


def generation_root(base_root: str, generation: int = 1) -> str:
    """纪律⑧：解析代际平行根；``v1`` = 基名，``vN`` = ``<base>_vN``。

    **拒绝符号链接根**（含中间目录）：符号链接会让"整根回滚"变成改写别处的文件。
    只校验路径形状与链接位，不创建目录（创建仍归 store.connect）。
    """
    require_non_empty(base_root, "generation_root(base_root)")
    if generation < 1:
        raise ValueError("memory generation must be >= 1")
    root = base_root if generation == 1 else f"{base_root}{GENERATION_ROOT_SUFFIX}{generation}"
    if os.path.islink(root):
        raise ValueError(f"memory root {root!r} is a symlink; generation roots must be real directories")
    probe = root
    while True:
        parent = os.path.dirname(probe)
        if not parent or parent == probe:
            break
        if os.path.islink(parent):
            raise ValueError(f"memory root {root!r} sits under a symlinked parent {parent!r}")
        probe = parent
    return root


@dataclass(frozen=True, slots=True)
class WritePolicy:
    """写回纪律的旋钮（装配期注入；默认值即 v3 §6.4 的口径）。"""

    attributed_to: str = "assistant"
    record_budget_bytes: int = MAX_RECORD_BYTES
    apply_redaction: bool = True
    apply_media_placeholder: bool = True
    enforce_record_budget: bool = True


def prepare_write(
    text: str,
    *,
    kind: MemoryWriteKind = MemoryWriteKind.DAILY,
    scope: MemoryScope = MemoryScope.USER,
    policy: WritePolicy | None = None,
    note: str | None = None,
    expires_at: datetime | None = None,
) -> MemoryWrite:
    """按纪律清洗一段正文并产出 typed 写载荷（唯一写路径仍经 ``WriteMemory``）。

    顺序固定：媒体占位 → 脱敏 → 单条预算截断 → 归因/过期位。截断**明写丢弃字节数**，
    不静默（静默截断是"记忆看着完整其实缺一半"的病根）。
    """
    active = policy or WritePolicy()
    body = text
    if active.apply_media_placeholder:
        body = media_placeholder(body)
    if active.apply_redaction:
        body = redact_inbound(body)
    body = body.strip()
    raw = body.encode("utf-8")
    if active.enforce_record_budget and len(raw) > active.record_budget_bytes:
        kept = raw[: active.record_budget_bytes].decode("utf-8", errors="ignore")
        body = f"{kept}\n[record truncated: dropped {len(raw) - active.record_budget_bytes} bytes]"
    if not body.strip():
        raise ValueError("prepare_write produced an empty record after discipline pass")
    return MemoryWrite(
        kind=kind,
        scope=scope,
        text=body,
        note=note,
        attributed_to=active.attributed_to,
        expires_at=expires_at,
    )


def with_attribution(write: MemoryWrite, attributed_to: str) -> MemoryWrite:
    """纪律⑤：改写归因位（frozen 载荷用 replace；用户声明优先于模型推断）。"""
    return replace(write, attributed_to=attributed_to)


__all__ = [
    "GENERATION_ROOT_SUFFIX",
    "MAX_EXTRACT_BYTES",
    "MAX_RECORD_BYTES",
    "MEDIA_PLACEHOLDER",
    "MIN_RATE_LIMIT_REMAINING_PERCENT",
    "NOT_A_COMPLETE_HISTORY",
    "TIER_RETENTION_DAYS",
    "WritePolicy",
    "bounded_extract",
    "generation_root",
    "media_placeholder",
    "prepare_write",
    "quota_allows",
    "redact_inbound",
    "retention_expiry",
    "with_attribution",
]
