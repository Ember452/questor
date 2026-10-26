"""`input_session.py`：非 TTY 回退。"""

from __future__ import annotations

import sys

from questorharness.bootstrap.hosts.terminal import input_session


def test_non_tty_host_falls_back_to_none(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """管道/CI 上必须回退裸 input，否则 `--prompt` 与脚本化调用全断。"""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert input_session.build({"/help": "Show help"}) is None
