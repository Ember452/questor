"""`paste.py`：括号粘贴标记、多行确认、图片粘贴识别。"""

from __future__ import annotations

from questorharness.bootstrap.hosts.terminal import paste


def test_bracketed_paste_markers_are_stripped() -> None:
    wrapped = f"{paste.BRACKETED_PASTE_START}hello{paste.BRACKETED_PASTE_END}"
    assert paste.normalize(wrapped) == "hello"


def test_crlf_is_normalized_to_lf() -> None:
    assert paste.normalize("a\r\nb") == "a\nb"


def test_single_line_paste_needs_no_confirmation() -> None:
    assert paste.needs_confirmation("git status") is False


def test_multiline_paste_needs_confirmation() -> None:
    """粘贴日志的第二行可能长得像命令，回车不能直接执行。"""
    assert paste.needs_confirmation("first line\nrm -rf build") is True


def test_blank_lines_do_not_trigger_confirmation() -> None:
    assert paste.needs_confirmation("only line\n\n  \n") is False


def test_image_paste_is_recognized() -> None:
    assert paste.is_image_paste("\x1b]1337;File=inline=1;base64,AAAA") is True
    assert paste.is_image_paste("data:image/png;base64,AAAA") is True
    assert paste.is_image_paste("just text") is False


def test_text_is_never_rewritten_beyond_markers() -> None:
    """归一化只动换行与包裹标记，其余内容一字不改（代码片段常含空格与缩进）。"""
    assert paste.normalize("  indented\n\tTabbed  ") == "  indented\n\tTabbed  "
