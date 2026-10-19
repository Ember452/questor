"""L2 内核可恢复压缩的**纯决策**（ADR-0048；design/01 I2；HARD C19/C2/C18）。

本模块只做**无 IO 的纯函数**：给定当前 `Run` + `CompactionConfig` + 累计 token，算出「要不要压缩、
逐出哪一段、摘要文本、可恢复锚」的 `CompactPlan`。真正的 IO（发 `pre_compact` 检查点、经 controller
提交 `CompactContext`）留在 `kernel/loop.py`。**摘要/`covered_hash` 在这里算好后随命令携带**，使
`state/reduce.py` 保持纯函数（对抗评审 MAJ-8）——回放时 `reduce` 只重放已携带的值、绝不重算摘要。

铁律：
- 逐出窗口只在 `closed_prefix(items)` 之内截断（C19：绝不孤儿化未闭合 `tool_use`）；
- 保头（system/首个 user 轮）保尾（最新可见回复），只压中段（design/01 §2「user/assistant 文本不删」的
  可恢复实现：中段进 `summary` + `recovery_pointers`，原文仍在 append-only `event_log`）；
- `covered_hash` 剔除易变字段（message id / seq / tool_use_id / args），只留语义形状，跨 rebuild 稳定
  （wuu compaction_note.go:74-75，ADR-0024）。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass

from questor.contracts.memory import RecoveryPointer
from questor.contracts.policy import CompactionConfig
from questor.contracts.state_schema import Message
from questor.state.checkpoint import closed_prefix
from questor.state.domain_state import Run

#: 摘要文本的字符上限（有界，承 C18；超限截断——完整原文靠 `recovery_pointers`→`event_log` 回读）。
_SUMMARY_MAX_CHARS = 4000


@dataclass(frozen=True, slots=True)
class CompactPlan:
    """纯决策产物；loop 据此发 `pre_compact` 检查点 + 提交 `CompactContext` 命令。"""

    evict_start: int
    evict_end: int
    summary_text: str
    new_floor: int
    new_pointers: tuple[RecoveryPointer, ...]


def _canonical(messages: Sequence[Message]) -> str:
    """把消息序列规范化成**只含语义形状**的 JSON：role + block.type + text。

    刻意剔除易变字段（message id、per-run seq、tool_use_id、args/input）——它们跨 rebuild/重放会变，
    留在锚里会让 `covered_hash` 校验假阴（fail-closed 误拒合法恢复）。"""
    shape = [
        {
            "role": m.role.value,
            "blocks": sorted(
                {"type": b.type, "text": b.text or ""} for b in m.content
            ),
        }
        for m in messages
    ]
    return json.dumps(shape, sort_keys=True, ensure_ascii=False, allow_nan=False)


def covered_hash(messages: Sequence[Message]) -> str:
    """被压区间的语义锚哈希（fail-closed 校验基准；ADR-0024/0048）。"""
    digest = hashlib.sha256(_canonical(messages).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def summarize(evicted: Sequence[Message]) -> str:
    """确定性启发式摘要（无 LLM、可复现）：拼接被压消息的可见文本。

    真 LLM 摘要质量是另一回事（标 UNVERIFIED）；本路径保证 eval/回放的确定性。"""
    parts: list[str] = []
    for m in evicted:
        text = " ".join(b.text for b in m.content if b.type == "text" and b.text)
        if text:
            parts.append(f"{m.role.value}: {text}")
    summary = "\n".join(parts).strip()
    if not summary:
        # 被压区全是 tool 块、无可见文本：仍产非哨兵浓缩标记，保证 reduce 的 summary 非空判据通过。
        summary = f"[compacted {len(evicted)} turn(s): tool activity only]"
    return summary[:_SUMMARY_MAX_CHARS]


def plan_compaction(run: Run, config: CompactionConfig, total_tokens: int) -> CompactPlan | None:
    """纯决策：该不该压、压哪段。不满足触发或无安全可压中段时返回 ``None``（不压缩）。

    失败一律返回 None（保守、绝不误截）；实际截断边界由 `reduce` 的 `closed_prefix` 二次把关（纵深）。"""
    items = run.context.items
    n = len(items)
    if n <= config.keep_head + config.keep_tail:
        return None  # 头尾保护区已覆盖全部，无中段可压
    triggered = (config.trigger_tokens is not None and total_tokens >= config.trigger_tokens) or (
        config.max_items is not None and n > config.max_items
    )
    if not triggered:
        return None
    cut = closed_prefix(items)
    evict_start = config.keep_head
    evict_end = min(cut, n - config.keep_tail)
    if evict_end <= evict_start:
        return None  # cut 落在头保护区内、或尾保护区内有未闭合调用 → 无安全可压窗口
    evicted = items[evict_start:evict_end]
    # 锚用**压缩前消息索引范围**（非 message.seq 字段）：`recovery_pointers` 指向 pre_compact 全量快照里
    # 被逐区的位置，读侧消费者（``kernel/recovery.verify_recovery_anchors``）据此切片原文、重算 ``covered_hash``
    # 校验、篡改即 fail-closed（Major-2 回读消费者）。索引与 evict 窗口逐字一致。
    pointer = RecoveryPointer(seq_from=evict_start, seq_to=evict_end - 1, covered_hash=covered_hash(evicted))
    return CompactPlan(
        evict_start=evict_start,
        evict_end=evict_end,
        summary_text=summarize(evicted),
        new_floor=evict_end,
        new_pointers=(pointer,),
    )
