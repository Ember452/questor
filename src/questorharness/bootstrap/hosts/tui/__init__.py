"""全屏 TUI 宿主（Textual）：终端即产品本体。

`app` 里是唯一的实现；本包只暴露 `run_tui`（装配好 serve 宿主后进入界面）。
"""

from __future__ import annotations

from questorharness.bootstrap.hosts.tui.app import QuestorApp, run_tui

__all__ = ["QuestorApp", "run_tui"]
