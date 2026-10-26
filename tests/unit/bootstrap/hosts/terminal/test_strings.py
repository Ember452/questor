"""`strings.py` 的契约：文案集中、占位符完整、空态可渲染。"""

from __future__ import annotations

from questorharness.bootstrap.hosts.terminal import strings


def test_badge_format_declares_every_placeholder() -> None:
    """格式串必须正好用 mark / gap_id / name 三个占位符，多一个少一个都会崩。"""
    assert set(_placeholders(strings.BADGE_FORMAT)) == {"mark", "gap_id", "name"}


def test_badge_format_renders_with_the_mark() -> None:
    """渲染结果以徽标起始符开头，终端里一眼能认出这是占位。"""
    text = strings.BADGE_FORMAT.format(mark=strings.BADGE_MARK, gap_id="A1", name="审批第三档")
    assert text.startswith(strings.BADGE_MARK)
    assert "A1" in text and "审批第三档" in text


def test_placeholder_is_a_single_visible_glyph() -> None:
    """FooterVM 缺数据时用可见占位，而不是空白（空白等于静默）。"""
    assert strings.PLACEHOLDER == "—"


def test_prompt_and_continuation_end_with_a_space() -> None:
    """提示符后必须留一个空格，否则用户输入会贴住符号。"""
    assert strings.PROMPT.endswith(" ")
    assert strings.CONTINUATION.endswith(" ")


def test_prompt_marker_keeps_the_glyph_when_the_host_can_encode_it() -> None:
    """UTF-8 宿主直接用完整的提示符。"""
    assert strings.prompt_marker("utf-8") == strings.PROMPT


def test_prompt_marker_falls_back_on_a_code_page_that_cannot_encode_it() -> None:
    """cp936 控制台写 `\\u276f` 会 UnicodeEncodeError（实跑撞过），必顶退 ASCII。"""
    assert strings.prompt_marker("gbk") == strings.PROMPT_FALLBACK


def test_prompt_marker_falls_back_on_an_unknown_encoding() -> None:
    """未知编码名不能把 REPL 卡死，只能降级。"""
    assert strings.prompt_marker("no-such-codec") == strings.PROMPT_FALLBACK


def test_prompt_marker_defaults_to_the_live_stdout_encoding(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """不传参时看真实 stdout 编码（管道/重定向下的宿主编码）。"""
    from types import SimpleNamespace

    monkeypatch.setattr(strings.sys, "stdout", SimpleNamespace(encoding="gbk"))
    assert strings.prompt_marker() == strings.PROMPT_FALLBACK


def test_empty_state_has_usage_lines() -> None:
    """空态至少要给出“怎么开始”和一条键位提示。"""
    assert len(strings.EMPTY_STATE_LINES) >= 2
    assert all(line.strip() for line in strings.EMPTY_STATE_LINES)


def _placeholders(template: str) -> list[str]:
    """取出 `{name}` 形式的占位符名（本项目只用简单占位符，不处理格式说明符）。"""

    import re

    return re.findall(r"\{([a-z_]+)\}", template)
