"""terminal_theme 纯函数测试：图标映射、回合页脚、状态条。"""

from __future__ import annotations

from questorharness.bootstrap.hosts.serve import terminal_theme as theme


def test_tool_status_icons() -> None:
    """三态图标对齐 Reasonix ToolCard 的 STATUS 表。"""
    assert theme.TOOL_STATUS["running"][0] == "▸"
    assert theme.TOOL_STATUS["done"][0] == "✓"
    assert theme.TOOL_STATUS["error"][0] == "✗"


def test_turn_footer_completed_with_usage() -> None:
    """完成回合：绿 ✓ + 耗时（秒）+ token（文案由 strings.OUTCOME_LABELS 提供）。"""
    text = theme.turn_footer("完成", 1200, {"inputTokens": 100, "outputTokens": 50})
    assert "✓ 完成" in text.plain
    assert "1.2s" in text.plain
    assert "100→50 tok" in text.plain


def test_turn_footer_failed() -> None:
    text = theme.turn_footer("失败", 500)
    assert "✗ 失败" in text.plain
    assert "0.5s" in text.plain


def test_approval_header_contains_tool_and_subject() -> None:
    text = theme.approval_header("bash", "echo hi")
    assert "需要审批" in text.plain
    assert "bash" in text.plain
    assert "echo hi" in text.plain


def test_status_bar_busy_vs_idle() -> None:
    idle = theme.status_bar("coding", "deepseek-flash", busy=False)
    busy = theme.status_bar("coding", "deepseek-flash", busy=True)
    assert "空闲" in idle.plain
    assert "回合进行中" in busy.plain


def test_notice_bar_error_vs_info() -> None:
    err = theme.notice_bar("bad thing", "error")
    info = theme.notice_bar("just saying", "info")
    assert "✗" in err.plain
    assert "·" in info.plain
