"""`markdown.py` 的契约：流式块状态机不把半截语法渲染出去。"""

from __future__ import annotations

from questorharness.bootstrap.hosts.terminal import markdown


def test_plain_text_streams_immediately() -> None:
    """没有块语法时不要缓冲：逐字流式是终端体验的底线。"""
    assert markdown.feed("你好") == ("你好", "")
    assert markdown.feed("你好 ") == ("你好 ", "")


def test_open_fence_is_held_back_until_it_closes() -> None:
    """未闭合 ``` 会把后续所有文本吞进代码块：必须押住不渲染。"""
    pending = ""
    emit, pending = markdown.feed("说明\n```python\nprint(1)")
    assert emit == "说明\n"
    assert pending == "```python\nprint(1)"
    emit, pending = markdown.feed(pending + "\n```\n")
    assert emit.endswith("```\n")
    assert pending == ""


def test_half_written_table_row_is_held_back() -> None:
    """表格必须整行到达才渲染，否则会先渲染半行再重画。"""
    emit, pending = markdown.feed("| a | b |\n| -")
    assert emit == "| a | b |\n"
    assert pending == "| -"


def test_half_written_list_item_is_held_back() -> None:
    emit, pending = markdown.feed("- 完成第一项\n- 第")
    assert emit == "- 完成第一项\n"
    assert pending == "- 第"


def test_flush_releases_everything_left() -> None:
    """回合结束时必须 flush，否则最后一段永远不显示。"""
    assert markdown.flush("| a |") == "| a |"
    assert markdown.flush("") == ""


def test_fence_marker_must_start_a_line() -> None:
    """行内的 ```（例如解释语法）不构成围栏。"""
    emit, pending = markdown.feed("用 ``` 包住代码\n")
    assert emit == "用 ``` 包住代码\n"
    assert pending == ""


def test_long_text_without_newline_is_not_buffered() -> None:
    """长段落没有换行也必须持续输出，不能等到换行才吐。"""
    text = "很长的一段话" * 20
    emit, pending = markdown.feed(text)
    assert emit
    assert emit + pending == text


def test_block_kind_labels_the_pending_buffer() -> None:
    """缓冲中的块要能被界面标出来（“正在写代码块”），而不是无声等待。"""
    assert markdown.block_kind("```python\nx") == "fence"
    assert markdown.block_kind("| a |") == "table"
    assert markdown.block_kind("- item") == "list"
    assert markdown.block_kind("段落") == "text"
