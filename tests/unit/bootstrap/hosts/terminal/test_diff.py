"""`diff.py` 的契约：把审批 detail 字符串渲染成可读的 diff 卡。"""

from __future__ import annotations

from rich.console import Console

from questorharness.bootstrap.hosts.terminal import diff, strings

DETAIL = """+2/-1
--- a/app.py
+++ b/app.py
@@ -1,3 +1,4 @@
 def run():
-    return 1
+    value = 2
+    return value
"""


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


def test_stats_header_is_kept() -> None:
    """首行 `+n/-m` 是审批卡最关键的摘要，不能被 diff 渲染吞掉。"""
    assert "+2/-1" in _plain(diff.render_detail(DETAIL))


def test_added_and_removed_lines_are_distinguishable() -> None:
    text = _plain(diff.render_detail(DETAIL))
    assert "+    value = 2" in text
    assert "-    return 1" in text


def test_hunk_header_is_shown() -> None:
    assert "@@ -1,3 +1,4 @@" in _plain(diff.render_detail(DETAIL))


def test_file_headers_are_shown() -> None:
    text = _plain(diff.render_detail(DETAIL))
    assert "--- a/app.py" in text
    assert "+++ b/app.py" in text


def test_truncated_patch_says_so() -> None:
    """authority 只给 4000 字符；到顶时必须在卡里说明被截断。"""
    long_detail = "+9/-9\n" + ("+x\n" * 2000)
    text = _plain(diff.render_detail(long_detail))
    assert strings.DIFF_TRUNCATED in text


def test_empty_detail_renders_nothing() -> None:
    assert _plain(diff.render_detail("")) .strip() == ""


def test_plain_text_detail_without_patch_still_renders_the_stats() -> None:
    """非编辑类审批的 detail 可能只有 `+0/-0` 或一句说明。"""
    assert "+0/-0" in _plain(diff.render_detail("+0/-0"))


def test_long_lines_are_wrapped_not_clipped() -> None:
    """长行必须换行显示，不能悄悄截掉内容（审批要看清改了什么）。"""
    detail = "+1/-0\n+" + ("y" * 200) + "\n"
    text = _plain(diff.render_detail(detail))
    assert text.count("y") >= 200
