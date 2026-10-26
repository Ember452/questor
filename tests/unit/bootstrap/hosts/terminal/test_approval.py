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


def test_toolbar_text_shows_deadline_and_remaining() -> None:
    """倒计时工具条：既说明超时后果，也给出剩余秒数（每秒重算）。"""

    line = approval.toolbar_text(310.0, now=10.0)
    assert "300 秒内未回答将自动拒绝" in line
    assert "倒计时 300s" in line
    assert "倒计时 0s" in approval.toolbar_text(10.0, now=10.0)


def test_countdown_session_is_none_off_tty(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """非 TTY 不得建交互会话（回退裸 input，CI/管道仍可用）。"""

    import sys

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert approval.build_session(300) is None


def test_countdown_session_passes_a_refreshing_toolbar(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """TTY 上建 PromptSession，并带每秒刷新的底部工具条（无头环境不能真开局，用探针断言入参）。"""

    import sys

    import prompt_toolkit

    captured: dict[str, object] = {}

    class _FakeSession:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(prompt_toolkit, "PromptSession", _FakeSession)

    assert approval.build_session(300, kind="提问") is not None
    assert captured.get("refresh_interval") == 1.0
    toolbar = captured.get("bottom_toolbar")
    assert callable(toolbar)
    assert "倒计时" in toolbar().value


def test_countdown_session_falls_back_when_the_host_has_no_console(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """无控制台宿主（CI/无头）构造会抛：必须退成 None，而不是把 REPL 带崩。"""

    import sys

    import prompt_toolkit

    class _Boom:
        def __init__(self, **kwargs: object) -> None:
            raise RuntimeError("no console")

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(prompt_toolkit, "PromptSession", _Boom)
    assert approval.build_session(300) is None
