"""Headless guard for the interactive terminal UI.

REPL 经 react_launcher 拉起 Node Ink;无 TTY 时 Ink 以原始堆栈崩溃
(2026-10-24 功能巡检实测)。守卫把崩溃换成一句干净报错与 ``--print``
指引。判死刀(plan 02 阶段 2)落地后,本测试随交互路径一起消失。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_interactive_repl_refuses_a_non_tty_stdin_with_a_clean_error():
    result = subprocess.run(
        [sys.executable, "-m", "questor"],
        cwd=REPO_ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0, "non-TTY stdin must not exit 0"
    assert "--print" in combined, "the error must point at the headless path"
    assert "TTY" in combined or "tty" in combined
    # 崩溃换报错:不允许再把 Ink 的内部堆栈倒给用户。
    assert "Raw mode" not in combined
    assert "ink" not in combined.lower()
