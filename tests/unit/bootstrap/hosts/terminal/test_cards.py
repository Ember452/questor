"""`cards.py` 的契约：七种对话图元 + 徽标 + 降级行。"""

from __future__ import annotations

from rich.console import Console

from questorharness.bootstrap.hosts.terminal import cards, strings, unsupported, wire_view as view
from questorharness.bootstrap.hosts.serve import terminal_theme as theme


def _plain(renderable: object) -> str:
    console = Console(
        width=100,
        color_system=None,
        legacy_windows=False,
        safe_box=True,
        emoji=False,
        record=True,
        file=None,
    )
    console.print(renderable)
    return console.export_text()


def test_tool_result_card_shows_status_icon_name_and_preview() -> None:
    item = view.ToolResultItem(tool_call_id="c1", tool="bash", output="全部通过\n第二行", is_error=False)
    text = _plain(cards.render_item(item))
    assert "bash" in text
    assert theme.TOOL_STATUS["done"][0] in text
    assert "全部通过" in text
    assert "第二行" not in text  # 卡片只取首行预览，展开由覆盖层负责


def test_failed_tool_card_uses_the_error_icon() -> None:
    item = view.ToolResultItem(tool_call_id="c1", tool="bash", output="boom", is_error=True)
    text = _plain(cards.render_item(item))
    assert theme.TOOL_STATUS["error"][0] in text


def test_tool_dispatch_renders_as_running() -> None:
    text = _plain(cards.render_item(view.ToolDispatchItem(tool_call_id="c1", tool="grep")))
    assert theme.TOOL_STATUS["running"][0] in text
    assert "grep" in text


def test_approval_card_offers_two_choices_and_points_at_the_mode_picker() -> None:
    item = view.ApprovalItem(
        prompt_id="p1", tool="edit_file", subject="a.py", detail="+1/-2\n@@ -1 +1 @@"
    )
    text = _plain(cards.render_item(item))
    assert "需要审批" in text
    assert "edit_file" in text
    assert "a.py" in text
    assert "+1/-2" in text
    assert ":mode" in text  # 第三档已落地（A1 注销）：指到 /permissions 三态换档


def test_ask_card_shows_the_question_and_the_answer_hint() -> None:
    text = _plain(cards.render_item(view.AskItem(prompt_id="p2", question="选哪个模式？")))
    assert "选哪个模式？" in text
    assert strings.ASK_HINT in text


def test_ask_card_numbers_its_options_and_drops_the_badge() -> None:
    """A2 落地后：选项编号可见，且不再挂“未实现”徽标。"""

    item = view.AskItem(prompt_id="p1", question="选哪个？", options=("保守", "激进"))
    text = _plain(cards.render_item(item))
    assert "1. 保守" in text and "2. 激进" in text
    assert "未实现" not in text


def test_notice_card_marks_errors_visibly() -> None:
    error = _plain(cards.render_item(view.NoticeItem(level="error", text="连接失败")))
    info = _plain(cards.render_item(view.NoticeItem(level="info", text="已切换")))
    assert "连接失败" in error and "✗" in error
    assert "已切换" in info


def test_compaction_card_shows_phase_or_trigger() -> None:
    started = _plain(cards.render_item(view.CompactionStartedItem(trigger="auto")))
    progress = _plain(
        cards.render_item(view.CompactionProgressItem(phase="compact_retry", attempt=2, message="重试"))
    )
    done = _plain(cards.render_item(view.CompactionDoneItem(trigger="auto", ok=True)))
    assert "上下文压缩" in started and "auto" in started
    assert "compact_retry" in progress and "2" in progress
    assert "上下文压缩" in done


def test_turn_done_card_shows_outcome_duration_and_usage() -> None:
    item = view.TurnDoneItem(
        turn_id="t-1",
        cancelled=False,
        outcome="completed",
        duration_ms=1200,
        checkpoint_turn=False,
        usage=view.UsageVM(input_tokens=3, output_tokens=5),
    )
    text = _plain(cards.render_item(item))
    assert "completed" in text
    assert "1200" in text
    assert "3" in text and "5" in text


def test_stream_reset_is_visible_not_silent() -> None:
    text = _plain(cards.render_item(view.StreamResetItem(reason="replay_gap")))
    assert "replay_gap" in text


def test_unsupported_item_renders_a_visible_degradation() -> None:
    text = _plain(cards.render_item(view.UnsupportedItem(kind="future_kind", reason="未登记的帧 kind")))
    assert "future_kind" in text
    assert "未登记的帧 kind" in text


def test_message_item_renders_text_and_marks_tool_blocks() -> None:
    item = view.MessageItem(
        blocks=(
            view.TextBlockVM(text="做完了"),
            view.ToolUseBlockVM(tool_use_id="c1", name="bash"),
            view.ImageBlockVM(media_type="image/png"),
        ),
        usage=None,
    )
    text = _plain(cards.render_item(item))
    assert "做完了" in text
    assert "bash" in text
    assert "image/png" in text


def test_say_stream_renders_markdown_without_a_card_wrapper() -> None:
    """流式正文不能套卡片：套上就变成每次 delta 重画一个盒子。"""
    text = _plain(cards.say_stream("**加粗**\n\n```py\nx = 1\n```\n"))
    assert "加粗" in text
    assert "x = 1" in text


def test_todos_card_shows_path_progress_and_marks() -> None:
    """W-D4：清单卡要有路径、完成计数与逐项勾选态。"""
    item = view.TodosItem(
        path="TODO.md",
        rows=(view.TodoRow(text="写文档", checked=True), view.TodoRow(text="补测试", checked=False)),
    )
    text = _plain(cards.render_item(item))
    assert "TODO.md" in text
    assert "1/2" in text
    assert theme.TODO_CHECKED in text and theme.TODO_OPEN in text
    assert "写文档" in text and "补测试" in text


def test_names_used_by_the_renderer_are_exported() -> None:
    for name in ("render_item", "say_stream", "empty_state", "banner"):
        assert hasattr(cards, name), name
    assert strings.EMPTY_STATE_LINES  # 空态文案在 strings 里，卡片只取用
