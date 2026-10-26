"""`width.py` 的契约：宽度只认 rich.cells，截断/折行不破组合字符。"""

from __future__ import annotations

import rich.cells

from questorharness.bootstrap.hosts.terminal import width

SAMPLES = (
    "abc",
    "中文abc",
    "全角：，。",
    "🙂🙂",
    "e\u0301combining",
    "mixed 中文 🙂 ok",
)


def test_cell_len_matches_rich_on_every_sample() -> None:
    """双真源是终端错行的经典来源：这里必须与 rich.cells 逐字符一致。"""
    for sample in SAMPLES:
        assert width.cell_len(sample) == rich.cells.cell_len(sample), sample


def test_cell_len_expands_tabs_like_a_terminal() -> None:
    """Tab 在 rich 里宽度是 0，直接渲染会把行算短；按终端语义对齐到下个制表位。"""
    assert width.cell_len("\t") == 4
    assert width.cell_len("a\tb") == 5  # 列 1 → 下一个制表位是 4，所以 3 个空格加 b
    assert width.cell_len("abcd\tb") == 9


def test_cell_len_drops_control_characters() -> None:
    """控制字符不该计入宽度（它们会把终端光标搞乱）。"""
    assert width.cell_len("a\x00b\x07c") == 3


def test_truncate_never_exceeds_the_budget() -> None:
    for sample in SAMPLES:
        for budget in (0, 1, 3, 5, 8, 20):
            clipped = width.truncate(sample, budget)
            assert width.cell_len(clipped) <= budget, (sample, budget, clipped)


def test_truncate_keeps_short_text_intact() -> None:
    assert width.truncate("中文", 10) == "中文"


def test_truncate_adds_an_ellipsis_only_when_it_fits() -> None:
    """截断有可见信号，但预算不够放下省略号时宁可不加。"""
    assert width.truncate("abcdef", 4, ellipsis="…") == "abc…"
    assert width.truncate("abcdef", 1, ellipsis="…") == "a"


def test_truncate_does_not_split_a_combining_sequence() -> None:
    """e + 组合重音是一个字素簇：要么整个保留，要么整个舍弃。"""
    assert width.truncate("e\u0301e\u0301", 1) == "e\u0301"
    assert width.truncate("e\u0301e\u0301", 0) == ""


def test_wrap_preserves_every_character() -> None:
    text = "中文 🙂 混排 mixed text"
    lines = width.wrap(text, 7)
    assert all(width.cell_len(line) <= 7 for line in lines)
    assert "".join(lines).replace(" ", "") == text.replace(" ", "")


def test_wrap_returns_one_line_when_it_fits() -> None:
    assert width.wrap("短", 10) == ["短"]


def test_wrap_rejects_non_positive_budget() -> None:
    """宽度预算是调用方的契约错误，静默返回空会掩盖布局 bug。"""
    try:
        width.wrap("abc", 0)
    except ValueError:
        return
    raise AssertionError("budget=0 必须 ValueError")
