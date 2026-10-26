"""`paste.py`：括号粘贴标记与换行归一化。"""

from __future__ import annotations

from questorharness.bootstrap.hosts.terminal import paste


def test_bracketed_paste_markers_are_stripped() -> None:
    wrapped = f"{paste.BRACKETED_PASTE_START}hello{paste.BRACKETED_PASTE_END}"
    assert paste.normalize(wrapped) == "hello"


def test_crlf_is_normalized_to_lf() -> None:
    assert paste.normalize("a\r\nb") == "a\nb"


def test_text_is_never_rewritten_beyond_markers() -> None:
    """归一化只动换行与包裹标记，其余内容一字不改（代码片段常含空格与缩进）。"""
    assert paste.normalize("  indented\n\tTabbed  ") == "  indented\n\tTabbed  "
