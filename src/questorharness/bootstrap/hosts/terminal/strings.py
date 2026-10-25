"""终端界面文案：中文一等公民的唯一落点。

终端包内其余模块不得出现中文字面量（`tests/unit/bootstrap/hosts/terminal/`
的文案集中度用例守着）；命令名、工具名、模型名等标识符保持原样，不进这里。
"""

from __future__ import annotations

# ---- 未实现徽标（plan03 §5）--------------------------------------------
BADGE_MARK = "⊘"
BADGE_FORMAT = "{mark} 未实现 · {gap_id} {name}"

# ---- 输入框（形态取自 Reasonix `tui/chrome.go` 的提示符）------------------
PROMPT = "❯ "
CONTINUATION = "… "

# ---- 缺数据占位（FooterVM 的可选字段）-----------------------------------
PLACEHOLDER = "—"

# ---- 空态提示（对齐 Reasonix Hero 的一句话）-----------------------------
EMPTY_STATE_LINES = (
    "输入一句话开始，或 / 查看全部指令。",
    "↑↓ 翻历史 · Ctrl-C 中止回合 · Ctrl-D 退出",
)
