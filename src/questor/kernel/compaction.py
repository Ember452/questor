"""L2 内核可恢复压缩的**纯决策**（ADR-0048/ADR-0057；design/01 I2；design/07 §7；HARD C19/C2/C18）。

本模块只做**无 IO 的纯函数**：给定当前 `Run` + `CompactionConfig` + 累计 token，算出「要不要压缩、
逐出哪一段、摘要文本、可恢复锚」的 `CompactPlan`。真正的 IO（发 `pre_compact` 检查点、经 controller
提交 `CompactContext`）留在 `kernel/loop.py`。**摘要/`covered_hash` 在这里算好后随命令携带**，使
`state/reduce.py` 保持纯函数（对抗评审 MAJ-8）——回放时 `reduce` 只重放已携带的值、绝不重算摘要。

铁律：
- 逐出窗口只在 `closed_prefix(items)` 之内截断（C19：绝不孤儿化未闭合 `tool_use`）；
- **也不得把 `tool_result` 切成头部孤儿**（§7.2 缺陷 ⑤：`closed_prefix` 只单向定义，「其中每个
  `tool_use` 都已应答」不保证任意更短前缀也闭合，而 `evict_end = min(cut, n - keep_tail)` 是常规
  路径——下刀落在 `(tool_use@j, tool_result@k)` 之间就会让保留序列**开头就是一个没有 `tool_use`
  的 `tool_result`**，provider 强制配对 → 4xx）。收口见 :func:`legal_evict_end`；
- 保头（system/首个 user 轮）保尾（最新可见回复），只压中段（design/01 §2「user/assistant 文本不删」的
  可恢复实现：中段进 `summary` + `recovery_pointers`，原文仍在 append-only `event_log`）；
- **只折叠、不删除**：本模块没有任何“丢弃一条消息”的出口，逐出 = 进摘要 + 留锚；
- 白名单外的工具结果**不压**（§7.2 `COMPACTABLE_TOOLS`；写类结果不可重建）；
- `covered_hash` 剔除易变字段（message id / seq / tool_use_id / args），只留语义形状，跨 rebuild 稳定
  （ADR-0024）。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass

from questor.contracts.memory import RecoveryPointer
from questor.contracts.policy import COMPACTABLE_TOOLS, CompactionConfig
from questor.contracts.state_schema import Message
from questor.state.checkpoint import closed_prefix, open_tool_use_ids, tool_result_pairing
from questor.state.domain_state import Run

#: 摘要文本的字符上限（有界，承 C18；超限截断——完整原文靠 `recovery_pointers`→`event_log` 回读）。
SUMMARY_MAX_CHARS = 4000

#: §7.2 可见占位符：被逐出的工具结果在摘要里留一句“这里曾有内容、怎么取回”，
#: 使模型知道上下文被折叠过而不是凭空变短（形状取 Claude-Code `toolResultStorage.ts:34`）。
CLEARED_PLACEHOLDER = "[Old tool result content cleared]"

#: §7.3 熔断上限：连续这么多次压缩失败后**停止自动压缩**并发 `compact_warning`。
#: 没有它的代价写在 Claude-Code 的注释里（1,279 个会话、最高 3,272 次连续失败）。
MAX_CONSECUTIVE_COMPACT_FAILURES = 3


@dataclass(frozen=True, slots=True)
class CompactPlan:
    """纯决策产物；loop 据此发 `pre_compact` 检查点 + 提交 `CompactContext` 命令。

    ``trigger`` 是**来路**（`auto`/`manual`/`legacy`），随命令进 `CompactContext` 并原样出现在
    两条 compact 事件里——压缩是有代际的事件，不是就地裁剪（§7.1）。"""

    evict_start: int
    evict_end: int
    summary_text: str
    new_floor: int
    new_pointers: tuple[RecoveryPointer, ...]
    trigger: str = "auto"


@dataclass(frozen=True, slots=True)
class EvictWindow:
    """:func:`evict_window` 的返回：安全可逐出的区间与该区间内的消息（供摘要器端口消费）。"""

    evict_start: int
    evict_end: int
    evicted: tuple[Message, ...]
    trigger: str


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

    真 LLM 摘要质量是另一回事（标 UNVERIFIED）；本路径保证 eval/回放的确定性，也是
    `providers/fake.py::FakeSummarizer` 的实现基线。含工具结果的区间末尾追加
    :data:`CLEARED_PLACEHOLDER`（§7.2：让模型知道这里曾有内容）。"""
    parts: list[str] = []
    had_tool_result = False
    for m in evicted:
        text = " ".join(b.text for b in m.content if b.type == "text" and b.text)
        had_tool_result = had_tool_result or any(b.type == "tool_result" for b in m.content)
        if text:
            parts.append(f"{m.role.value}: {text}")
    if not parts:
        # 被压区全是 tool 块、无可见文本：仍产非哨兵浓缩标记，保证 reduce 的 summary 非空判据通过。
        parts.append(f"[compacted {len(evicted)} turn(s): tool activity only]")
    if had_tool_result:
        parts.append(CLEARED_PLACEHOLDER)
    summary = "\n".join(parts).strip()
    return summary[:SUMMARY_MAX_CHARS]


def evict_window(
    run: Run,
    config: CompactionConfig,
    total_tokens: int,
    *,
    trigger: str = "auto",
) -> EvictWindow | None:
    """算出**安全可逐出**的中段窗口；不满足触发或无安全窗口返回 ``None``（绝不勉强压）。

    四道收口，逐条对应 §7.2 的缺陷：
    ① 头尾保护区覆盖全部 → 无中段；
    ② 触发判据（绝对阈值或旧信号）不过 → 不压；
    ③ 白名单：区间内遇到不可压工具的结果就把右界收到它之前（写类结果不可重建）；
    ④ :func:`legal_evict_end`：把右界退到不产生**头部孤儿 `tool_result`** 的位置。
    """
    items = run.context.items
    n = len(items)
    if n <= config.keep_head + config.keep_tail:
        return None  # 头尾保护区已覆盖全部，无中段可压
    if not _triggered(run, config, total_tokens, trigger):
        return None
    cut = closed_prefix(items)
    evict_start = config.keep_head
    # 头边界必须落在“前缀 items[:start] 内每个 tool_use 都已应答”处，否则保留头区会留悬空
    # tool_use，下一轮 provider 前 _ensure_paired_history 判失败（WF-003）。
    evict_start = legal_evict_start(items, evict_start, min(cut, n - config.keep_tail))
    evict_end = min(cut, n - config.keep_tail)
    if evict_end <= evict_start:
        return None  # cut 落在头保护区内、或尾保护区内有未闭合调用 → 无安全可压窗口
    evict_end = _whitelist_cut(run, config, items, evict_start, evict_end)
    evict_end = legal_evict_end(items, evict_start, evict_end)
    if evict_end <= evict_start:
        return None
    return EvictWindow(
        evict_start=evict_start,
        evict_end=evict_end,
        evicted=tuple(items[evict_start:evict_end]),
        trigger=trigger,
    )


def _triggered(run: Run, config: CompactionConfig, total_tokens: int, trigger: str) -> bool:
    """触发判据：**绝对阈值优先**（§7.1）；未配 `context_window` 才逐字退回旧信号。

    `auto` 用 ``EW - max(摘要预留, 自动缓冲)``、`manual` 用更紧的 ``EW - 手动缓冲``；两条旧判据
    （`trigger_tokens` 累计用量 / `max_items` 条数）只在没有窗口信息时生效，语义与 P10 一致。"""
    threshold = config.threshold(trigger) if trigger in {"auto", "manual"} else None
    if threshold is not None:
        return total_tokens >= threshold
    if trigger != "auto":
        return False
    if config.trigger_tokens is not None and total_tokens >= config.trigger_tokens:
        return True
    return config.max_items is not None and len(run.context.items) > config.max_items


def _whitelist_cut(run: Run, config: CompactionConfig, items: Sequence[Message], evict_start: int, evict_end: int) -> int:
    """把右界收到**第一个不可压工具结果**之前（§7.2 白名单）。

    工具名从 `tool_ledger` 反查（`tool_result` 块自身不带名字）；查不到名字按不可压处理——
    宁可不压也不猜（与“写类结果不压”同向）。"""
    allowed = set(config.compactable())
    names = _tool_names(run)
    for index in range(evict_start, evict_end):
        for block in items[index].content:
            if block.type not in {"tool_use", "tool_result"} or not block.tool_use_id:
                continue
            name = names.get(block.tool_use_id)
            if name is None or name not in allowed:
                return index
    return evict_end


def _tool_names(run: Run) -> dict[str, str]:
    """``tool_use_id`` → 工具名（写侧只有 ledger 知道是谁 produced 这条结果）。"""
    return {call.tool_call_id: call.name for call in run.tool_ledger.calls if call.tool_call_id}


def legal_evict_start(items: Sequence[Message], evict_start: int, ceiling: int) -> int:
    """把左界推进到“保留头区 items[:start] 无悬空 tool_use”的位置（§7.2 WF-003）。

    `closed_prefix`/`legal_evict_end` 只防住尾部孤儿 `tool_result`；头侧对称缺陷——头区里某
    `tool_use` 的 `tool_result` 落在被逐出窗内——会使保留历史头部悬空。左界每前进一步重算一次
    （多逐出一些反而使配对完整），推进到 `ceiling` 仍不闭合则交给上层“无安全窗口→不压”。
    """
    start = evict_start
    while start < ceiling and open_tool_use_ids(tuple(items[:start])):
        start += 1
    return start


def legal_evict_end(items: Sequence[Message], evict_start: int, evict_end: int) -> int:
    """把右界退到“保留序列的第一个不是孤儿 `tool_result`”的位置（§7.2 缺陷 ⑤ / 前置闸门⑤）。

    `closed_prefix` 只保证前缀内每个 `tool_use` 都已应答，**不保证任意更短前缀也闭合**：
    当 `tool_use@j` 被逐出而它的 `tool_result@k` 留在保留尾（j < evict_end <= k），保留窗口
    开头就是没有 `tool_use` 的 `tool_result`，provider 会直接 4xx。逐出区间的配对来自
    :func:`questor.state.checkpoint.tool_result_pairing`，右界每退一步重算一次。
    """
    end = evict_end
    while evict_start < end < len(items):
        used, _produced = tool_result_pairing(items[evict_start:end])
        head_ids = {block.tool_use_id for block in items[end].content if block.type == "tool_result" and block.tool_use_id}
        if not head_ids & used:
            return end
        end -= 1
    return end


def plan_compaction(
    run: Run,
    config: CompactionConfig,
    total_tokens: int,
    *,
    trigger: str = "auto",
    summary_text: str | None = None,
) -> CompactPlan | None:
    """纯决策：该不该压、压哪段、摘要与锚。不满足条件返回 ``None``（不压缩，绝不误截）。

    ``summary_text`` 由 loop 异步调用 `SummarizerPort` 后传入（L2 不做 IO）；未给则用本模块的
    确定性启发式 :func:`summarize`。实际截断边界由 `reduce` 的 `closed_prefix` 二次把关（纵深）。
    """
    window = evict_window(run, config, total_tokens, trigger=trigger)
    if window is None:
        return None
    evicted = window.evicted
    # 锚用**压缩前消息索引范围**（非 message.seq 字段）：`recovery_pointers` 指向 pre_compact 全量快照里
    # 被逐区的位置，读侧消费者（``kernel/recovery.verify_recovery_anchors``）据此切片原文、重算 ``covered_hash``
    # 校验、篡改即 fail-closed（Major-2 回读消费者）。索引与 evict 窗口逐字一致。
    pointer = RecoveryPointer(seq_from=window.evict_start, seq_to=window.evict_end - 1, covered_hash=covered_hash(evicted))
    text = summarize(evicted) if summary_text is None else summary_text[:SUMMARY_MAX_CHARS]
    return CompactPlan(
        evict_start=window.evict_start,
        evict_end=window.evict_end,
        summary_text=text,
        new_floor=window.evict_end,
        new_pointers=(pointer,),
        trigger=window.trigger,
    )


__all__ = [
    "CLEARED_PLACEHOLDER",
    "COMPACTABLE_TOOLS",
    "MAX_CONSECUTIVE_COMPACT_FAILURES",
    "SUMMARY_MAX_CHARS",
    "CompactPlan",
    "EvictWindow",
    "covered_hash",
    "evict_window",
    "legal_evict_end",
    "plan_compaction",
    "summarize",
]
