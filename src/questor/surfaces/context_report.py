"""L6 只读观测面（B15 /context 与 /cost）：把"上下文里都装了什么、这次花了多少"讲给用户。

纪律（与 §13 B15 一致，也是本文件存在的理由）：

* **只读**：不取号、不写事件、不碰 reduce——所有数字都从 durable 事实与当前快照**投影**出来。
* **估算口径写在输出里**：仓内没有官方 tokenizer，token 一律按 ``chars / 4`` **估**并标注
  `estimate`；把估算当实测报（或按一个凭空的汇率报美元）就是骗人（§17-9）。
* **成本停在 token**：`run_completed.usage` 里没有钱；`--cost` 复用 B12 的 `per_task_cost`
  口径，没有价目表时明确 `cost_usd=UNVERIFIED`。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from questor.contracts.artifacts import OutputBudget
from questor.contracts.policy import CompactionConfig
from questor.contracts.tool import ToolSpec
from questor.kernel.recovery import rebuild_run
from questor.state.domain_state import Run
from questor.surfaces.logs import session_totals

#: token 估算口径（**估算**，不是实测；输出里必须带着这个词）。
CHARS_PER_TOKEN = 4

#: 一次全局重放的行数上限（`--cost` 跨 run 聚合用；超限就少算并明说，不假装算全）。
COST_REPLAY_LIMIT = 50_000


def estimate_tokens(chars: int) -> int:
    """把字符数换成**估算** token（向上取整，宁多报不少报）。"""
    return -(-max(0, int(chars)) // CHARS_PER_TOKEN)


def _spec_chars(spec: ToolSpec) -> int:
    """一个工具面条目进请求体的大致体积：名字 + 描述 + 参数 schema 的字符串化长度。"""
    return len(spec.name) + len(spec.description) + len(str(spec.params))


def context_segments(
    run: Run,
    *,
    system: str | None,
    tools: Sequence[ToolSpec],
    memory_index_chars: int = 0,
    compacted_by: int = 0,
) -> list[tuple[str, int, str]]:
    """把一次请求体拆成 ``(段名, 字符数, 注记)`。

    段划分与 §6.1 的 cache 段一致（system / 记忆索引子段 / 工具面 / 历史 / 摘要），
    所以这份账单和"哪一段把 cache 打断了"能对着看。`compacted_by` 是被折叠掉的字符数：
    它**必须显示**，否则用户看到的是一份假装完整的上下文（B10 的可信度就在这）。
    """
    history_chars = sum(len(block.text or "") for message in run.context.items for block in message.content if block.type == "text")
    summary = run.context.summary or ""
    segments: list[tuple[str, int, str]] = [("system", len(system or ""), "static prefix" if system else "no system prompt")]
    if memory_index_chars:
        segments.append(("memory-index", memory_index_chars, "delimited sub-section of system (read-only reference)"))
    segments.append(("tools", sum(_spec_chars(spec) for spec in tools), f"{len(tools)} tool specs"))
    segments.append(("history", history_chars, f"{len(run.context.items)} messages after folding"))
    if summary:
        segments.append(("summary", len(summary), "recovery summary of the folded middle"))
    if compacted_by:
        segments.append(("folded-out", compacted_by, "est. chars removed by compaction (originals stay in event_log)"))
    if run.context.recovery_pointers:
        segments.append(("anchors", len(run.context.recovery_pointers) * 72, "recovery pointers (hashes, no body)"))
    return segments


def format_context_report(run: Run, segments: Sequence[tuple[str, int, str]], *, window: CompactionConfig | None = None) -> str:
    """人读的一屏：分段明细 + 总量 + 阈值位置（配了窗口时才算得出"离溢出还有多远"）。"""
    lines = [f"context for run={run.run_id} (seq={run.seq}, turn={run.turn})"]
    total_chars = 0
    for name, chars, note in segments:
        total_chars += chars
        lines.append(f"  {name:<14}{chars:>9} chars ~{estimate_tokens(chars):>6} tokens (estimate)  # {note}")
    lines.append(f"  {'total':<14}{total_chars:>9} chars ~{estimate_tokens(total_chars):>6} tokens (estimate)")
    if window is not None and window.context_window is not None:
        auto = window.auto_threshold()
        warning = window.warning_threshold()
        lines.append(
            f"  window={window.context_window} max_output={window.max_output} "
            f"effective={window.effective_window()} auto_threshold={auto} warning_threshold={warning}"
        )
        if auto is not None:
            lines.append(f"  tokens before auto-compaction is refused: ~{max(0, auto - estimate_tokens(total_chars))} (estimate)")
    else:
        lines.append("  window: unknown (no context_window configured; compaction falls back to item counts)")
    lines.append("  budget: model_result_bytes per tool result = " f"{OutputBudget().model_result_bytes}")
    return "\n".join(lines)


def format_cost_report(totals: Mapping[str, int], succeeded: int, *, per_task_tokens: float | None) -> str:
    """把总量与“每成功任务”一起打印；成本标 UNVERIFIED（无价目表就没有美元数）。

    `per_task_tokens` 由调用方算：`--cost` 走 `surfaces.logs.session_totals`（ durable
    `run_completed.usage` 的唯一聚合口径）+ B12 的 `metrics.per_task_cost`，**不在这里重算**
    （同一口径写两份就会分叉）。None = 没有成功任务，比值不存在而不是 0。
    """
    lines = [
        "cost (projected from durable run_completed; token-level only)",
        f"  runs_completed={totals.get('runs_completed', 0)}",
        f"  input_tokens={totals.get('input_tokens', 0)}",
        f"  output_tokens={totals.get('output_tokens', 0)}",
        f"  total_tokens={totals.get('total_tokens', 0)}",
        f"  tokens_per_succeeded_task={per_task_tokens if per_task_tokens is not None else 'n/a (no succeeded tasks)'}",
        "  cost_usd=UNVERIFIED (no price table in-repo; see design §17-9)",
    ]
    if not succeeded:
        lines.append("  note: 0 succeeded tasks -> ratio is undefined, not zero")
    return "\n".join(lines)


async def context_report_for_run(store: object, surface: object, run_id: str) -> str:
    """从 durable 态重建 run 并出账单（**不依赖活 controller**：事后也能看）。

    `surface` 只用来取静态面（system / 工具名册 / compaction 窗口）；不驱动、不写库。
    无快照无事件时 `rebuild_run` 返回 None → 明说没什么可报，不编一份空的。
    """
    run = await rebuild_run(store, run_id)  # type: ignore[arg-type]
    if run is None:
        return f"no durable state for run={run_id} (no checkpoint and no events)"
    tools: Sequence[ToolSpec] = tuple(tool.spec for tool in surface.registry.list_available())  # type: ignore[attr-type]
    index_block = getattr(surface, "memory_index", None)
    index_chars = len(getattr(index_block, "text", "") or "") if index_block is not None else 0
    # 不传 `compacted_by`：存留快照里没有“被折叠掉多少字符”这个事实（它在事件里），
    # 猜一个数字比不报更糟——宁愿少一列，也不多一列假数。
    segments = context_segments(run, system=getattr(surface, "system", None), tools=tools, memory_index_chars=index_chars)
    return format_context_report(run, segments, window=getattr(surface, "compaction", None))


async def cost_report_for_store(store: object) -> str:
    """跨 run 的 token 账单：聚合口径 = `session_totals`（唯一 durable 用量真源）。

    每成功任务的 token 用 B12 同一份 `per_task_cost` 算（两边不会分叉）；没有价目表时
    它就是 token 级。重放行数超 `COST_REPLAY_LIMIT` 会**在输出里声明可能少算**，不假装算全。
    """
    rows = await store.replay_global(0, limit=COST_REPLAY_LIMIT)  # type: ignore[attr-type]
    totals = session_totals(rows)
    succeeded = int(totals["runs_completed"])
    per_task = round(totals["total_tokens"] / succeeded, 2) if succeeded else None
    lines = [format_cost_report(totals, succeeded, per_task_tokens=per_task)]
    if len(rows) >= COST_REPLAY_LIMIT:
        lines.append(f"  note: replay capped at {COST_REPLAY_LIMIT} rows -> these totals may be undercounted")
    return "\n".join(lines)


__all__ = [
    "CHARS_PER_TOKEN",
    "COST_REPLAY_LIMIT",
    "context_report_for_run",
    "context_segments",
    "cost_report_for_store",
    "estimate_tokens",
    "format_context_report",
    "format_cost_report",
]
