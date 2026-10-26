"""七种对话图元：把视图模型变成 rich 可渲染对象。

样式一律取 `serve/terminal_theme.py`（视觉真源），本模块只组合、不新增颜色；
中文文案取 `strings.py`。流式正文走 `say_stream()`，**不套卡片**——套上就变成
每来一个 delta 重画一个盒子。
"""

from __future__ import annotations

from collections.abc import Iterable

from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.text import Text

from questorharness.bootstrap.hosts.serve import terminal_theme as theme
from questorharness.bootstrap.hosts.terminal import diff as diff_card
from questorharness.bootstrap.hosts.terminal import strings, unsupported, width
from questorharness.bootstrap.hosts.terminal import wire_view as view


def _usage_dict(usage: view.UsageVM | None) -> dict[str, int] | None:
    if usage is None:
        return None
    return {"inputTokens": usage.input_tokens, "outputTokens": usage.output_tokens}


def banner() -> RenderableType:
    """启动横幅：一行品牌（形态行由调用方补）。"""

    return Text(theme.BANNER, style=theme.NET)


def empty_state() -> RenderableType:
    """空态：怎么开始 + 一条键位提示。"""

    text = Text()
    for index, line in enumerate(strings.EMPTY_STATE_LINES):
        if index:
            text.append("\n")
        text.append(line, style=theme.DIM)
    return text


def gaps() -> RenderableType:
    """启动时列出每一个已登记的缺口（只登记不显示等于把限制藏起来）。

    文案与徽标文本都取 `strings` / `unsupported`，本函数只负责拼成一行；
    `tests/ci/test_unsupported_badges.py` 反向禁止包内其他位置裸写徽标。
    """

    text = Text()
    text.append(strings.GAPS_LEAD, style=theme.DIM)
    for index, gap_id in enumerate(unsupported.UNSUPPORTED):
        if index:
            text.append(" · ", style=theme.DIM)
        text.append(unsupported.badge_text(gap_id), style=theme.DIM)
    return text


def say_stream(text: str) -> RenderableType:
    """流式正文：markdown 渲染，不加标题行、不加边框。"""

    return Markdown(text)


def _tool_card(item: view.ToolResultItem) -> RenderableType:
    """工具卡：`✓ tool` + `⎿ 结果首行`（两行节奏，结果按列宽截断）。"""

    first = ""
    if item.output and item.output.strip():
        first = item.output.strip().splitlines()[0]
    return theme.tool_card(
        item.tool, width.truncate(first, 120) if first else None, is_error=item.is_error
    )


def _approval_card(item: view.ApprovalItem) -> RenderableType:
    parts: list[RenderableType] = [theme.approval_header(item.tool, item.subject)]
    if item.patch is not None:
        # 结构化 diff（波 D2）：优先于旧 detail 字符串。
        parts.append(
            diff_card.render_patch(
                item.patch, added=item.added or 0, removed=item.removed or 0
            )
        )
    elif item.detail:
        parts.append(diff_card.render_detail(item.detail))
    parts.append(Text(strings.APPROVAL_CHOICES, style=theme.DIM))
    # A1 已落地：第三档不再是徽标，而是指到 :mode（引擎 /permissions 三态）。
    parts.append(Text(strings.APPROVAL_MODE_HINT, style=theme.DIM))
    return Group(*parts)


def _ask_card(item: view.AskItem) -> RenderableType:
    head = Text()
    head.append("  ? ", style=theme.ACCENT)
    head.append(item.question, style=theme.BOLD)
    parts: list[RenderableType] = [head]
    for index, option in enumerate(item.options, start=1):
        # 编号选项（plan03 A2）：用户可按序号回答，也可回原文。
        line = Text()
        line.append(f"   {index}. ", style=theme.NET)
        line.append(option)
        parts.append(line)
    parts.append(Text(strings.ASK_HINT, style=theme.DIM))
    return Group(*parts)


def _compaction_progress(item: view.CompactionProgressItem) -> RenderableType:
    text = theme.compaction_line("progress", "")
    text.append(f" {item.phase}", style=theme.DIM)
    if item.attempt > 1:
        text.append(f" ×{item.attempt}", style=theme.DIM)
    if item.message:
        text.append(f" · {item.message}", style=theme.DIM)
    return text


def _compaction_done(item: view.CompactionDoneItem) -> RenderableType:
    text = theme.compaction_line("done", item.trigger)
    if not item.ok:
        text.append(" · 失败", style=theme.ERR)
    return text


def _stream_reset(item: view.StreamResetItem) -> RenderableType:
    return theme.notice_bar(f"{strings.STREAM_RESET}（{item.reason}）", "warning")


def _todos(item: view.TodosItem) -> RenderableType:
    """清单卡（W-D4）：标题用路径，逐项勾选态。"""

    return theme.todo_card(item.path, [(row.text, row.checked) for row in item.rows])


def _unsupported(item: view.UnsupportedItem) -> RenderableType:
    text = Text()
    text.append(f"  {strings.UNSUPPORTED_LEAD} ", style=theme.WARN)
    text.append(item.kind, style=theme.BOLD)
    text.append(f" · {item.reason}", style=theme.DIM)
    return text


def _block_lines(blocks: Iterable[view.BlockVM]) -> RenderableType:
    parts: list[RenderableType] = []
    for block in blocks:
        if isinstance(block, view.TextBlockVM):
            parts.append(say_stream(block.text))
        elif isinstance(block, view.ToolUseBlockVM):
            # 块展开时不再逐条报 `工具 call <id> · name`：同一件事已经在
            # tool_dispatch/tool_result 卡里出现过一次，重复一次只是噪音。
            continue
        elif isinstance(block, view.ImageBlockVM):
            parts.append(
                Text(
                    "  " + strings.IMAGE_BLOCK.format(media_type=block.media_type),
                    style=theme.DIM,
                )
            )
        else:
            status = "error" if block.is_error else "done"
            parts.append(theme.tool_line(block.tool_use_id, status, block.content))
    return Group(*parts) if parts else Text("", style=theme.DIM)


def render_item(item: view.Item) -> RenderableType:
    """按视图模型类型分派；未覆盖的类型由最后一支兜底成可见降级行。"""

    if isinstance(item, view.TurnStartedItem):
        return theme.turn_header(item.turn_id)
    if isinstance(item, view.TextItem):
        return say_stream(item.text)
    if isinstance(item, view.MessageItem):
        return _block_lines(item.blocks)
    if isinstance(item, view.ToolDispatchItem):
        # `▸ bash  npm test`：工具行必须回答“它在干什么”。
        return theme.tool_line(item.tool, "running", item.detail or None)
    if isinstance(item, view.ToolResultItem):
        return _tool_card(item)
    if isinstance(item, view.NoticeItem):
        return theme.notice_bar(item.text, item.level)
    if isinstance(item, view.ApprovalItem):
        return _approval_card(item)
    if isinstance(item, view.AskItem):
        return _ask_card(item)
    if isinstance(item, view.CompactionStartedItem):
        return theme.compaction_line("started", item.trigger)
    if isinstance(item, view.CompactionProgressItem):
        return _compaction_progress(item)
    if isinstance(item, view.CompactionDoneItem):
        return _compaction_done(item)
    if isinstance(item, view.TurnDoneItem):
        return theme.turn_footer(
            strings.OUTCOME_LABELS.get(item.outcome, item.outcome),
            item.duration_ms,
            _usage_dict(item.usage),
        )
    if isinstance(item, view.StreamResetItem):
        return _stream_reset(item)
    if isinstance(item, view.TodosItem):
        return _todos(item)
    return _unsupported(item)
