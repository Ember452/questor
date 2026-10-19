"""#180：入口把 stdout/stderr 重配为 UTF-8，防非 UTF-8 代码页宿主 print CJK 崩。"""

from __future__ import annotations

import io

import pytest

from questor.surfaces._assembly import reconfigure_output_streams


def test_reconfigure_makes_cp1252_stream_utf8_safe() -> None:
    buf = io.BytesIO()
    bad = io.TextIOWrapper(buf, encoding="cp1252")
    with pytest.raises(UnicodeEncodeError):
        bad.write("中文")
        bad.flush()

    buf2 = io.BytesIO()
    ok = io.TextIOWrapper(buf2, encoding="cp1252")
    reconfigure_output_streams(ok)
    ok.write("中文")
    ok.flush()
    assert "中文".encode() in buf2.getvalue()


def test_reconfigure_noop_when_stream_lacks_reconfigure() -> None:
    class NoReconfigure:
        def write(self, *_a: object) -> int:
            return 0

    reconfigure_output_streams(NoReconfigure())  # 不抛即通过（pytest 捕获流场景）
