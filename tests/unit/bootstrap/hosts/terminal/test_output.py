"""`output.py`：给控制台的写端做编码降级，cp936 宿主不会因 `✓` 崩掉整条消费链。"""

from __future__ import annotations

import io


class GbkStream:
    """像 cp936 控制台一样：遇到装不下的字符直接抛 UnicodeEncodeError。"""

    encoding = "gbk"

    def __init__(self) -> None:
        self.written: list[str] = []

    def write(self, text: str) -> int:
        text.encode(self.encoding)
        self.written.append(text)
        return len(text)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False

    def value(self) -> str:
        return "".join(self.written)


def test_tolerant_stream_replaces_what_the_host_cannot_encode() -> None:
    from questorharness.bootstrap.hosts.terminal import output

    inner = GbkStream()
    stream = output.tolerant_stream(inner)
    stream.write("✓ completed")
    assert "completed" in inner.value()
    assert "✓" not in inner.value()


def test_tolerant_stream_passes_encodable_text_through_unchanged() -> None:
    from questorharness.bootstrap.hosts.terminal import output

    inner = GbkStream()
    stream = output.tolerant_stream(inner)
    stream.write("完成")
    assert inner.value() == "完成"


def test_tolerant_stream_forwards_flush_and_isatty() -> None:
    from questorharness.bootstrap.hosts.terminal import output

    stream = output.tolerant_stream(GbkStream())
    assert stream.isatty() is False
    stream.flush()


def test_console_writes_through_the_tolerant_stream() -> None:
    """端到端：控制台里的 `✓` 落到 gbk 流上不抛，只剩降级字符。"""

    from questorharness.bootstrap.hosts.terminal import output

    inner = GbkStream()
    console = output.console(inner)
    console.print("✓ done", highlight=False, markup=False)
    assert "done" in inner.value()


def test_tolerant_stream_keeps_working_with_a_plain_string_stream() -> None:
    """没有 `encoding` 的流（StringIO）按 utf-8 处理，不因为探测失败而降级一切。"""

    from questorharness.bootstrap.hosts.terminal import output

    buffer = io.StringIO()
    output.tolerant_stream(buffer).write("✓")
    assert buffer.getvalue() == "✓"
