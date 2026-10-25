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
from questorharness.bootstrap.hosts.terminal import strings, unsupported, wire_view as view


def _usage_dict(usage: view.UsageVM | None) -> dict[str, int] | None:
    if usage is None:
        return None
    return {"inputTokens": usage.input_tokens, "outputTokens": usage.output_tokens}


def _badge_line(gap_id: str) -> Text:
    text = Text()
    text.append("  ")
    text.append(unsupported.badge_text(gap_id), style=theme.DIM)
    return text


def banner() -> RenderableType:
    """启动横幅：Reasonix ASCII art（形态行由调用方补）。"""

    return Text(theme.BANNER, style=theme.NET)


def empty_state() -> RenderableType:
    """空态：怎么开始 + 一条键位提示。"""

    text = Text()
    for index, line in enumerate(strings.EMPTY_STATE_LINES):
        if index:
            text.append("\n")
        text.append(line, style=theme.DIM)
    return text


def say_stream(text: str) -> RenderableType:
    """流式正文：markdown 渲染，不加标题行、不加边框。"""

    return Markdown(text)


def _tool_card(item: view.ToolResultItem) -> RenderableType:
    status = "error" if item.is_error else "done"
    return theme.tool_line(item.tool, status, item.output)


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
    parts.append(_badge_line("A1"))
    return Group(*parts)


def _ask_card(item: view.AskItem) -> RenderableType:
    head = Text()
    head.append("  ? ", style=theme.ACCENT)
    head.append(item.question, style=theme.BOLD)
    return Group(head, Text(strings.ASK_HINT, style=theme.DIM), _badge_line("A2"))


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
            parts.append(
                Text(
                    "  "
                    + strings.TOOL_USE_BLOCK.format(
                        tool_use_id=block.tool_use_id, name=block.name
                    ),
                    style=theme.DIM,
                )
            )
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
        return theme.tool_line(item.tool, "running")
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
        return theme.turn_footer(item.outcome, item.duration_ms, _usage_dict(item.usage))
    if isinstance(item, view.StreamResetItem):
        return _stream_reset(item)
    return _unsupported(item)
