"""`approval.py`：截止提示与剩余时间（与服务端 300s 对齐）。"""

from __future__ import annotations

from questorharness.bootstrap.hosts.terminal import approval


def test_approval_hint_states_the_fail_closed_direction() -> None:
    hint = approval.deadline_hint(300)
    assert "300" in hint
    assert "拒绝" in hint
    assert "fail-closed" in hint


def test_ask_hint_says_empty_answer_instead_of_deny() -> None:
    hint = approval.deadline_hint(120, kind="提问")
    assert "120" in hint
    assert "未回答" in hint
    assert "拒绝" not in hint


def test_remaining_never_goes_negative() -> None:
    assert approval.remaining(0.0, now=10.0) == 0
    assert approval.remaining(130.0, now=10.0) == 120


def test_deadline_is_offset_from_now() -> None:
    assert approval.deadline_from(300, now=5.0) == 305.0
