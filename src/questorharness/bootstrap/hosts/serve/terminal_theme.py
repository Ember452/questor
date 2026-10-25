"""终端主题：Reasonix 设计法典（tokens.css / LAYOUT.md）的终端投影。

语义色一色一义（对齐 Reasonix tokens 的命名而非具体色值，终端 ANSI 能力有限）：
- accent  = 需要你注意（琥珀） → 审批、警告、待操作
- net     = 自持运行（蓝）     → 工具执行、回合活动
- ok      = 完成（绿）         → 成功、完成态
- err     = 错误（红）         → 失败、拒绝
- dim     = 辅助信息           → 分隔线、耗时、提示

间距/排版（终端投影，对应 Reasonix 的 spacing scale）：
- 行间留一空行（对应 --sp-8）
- 卡片标题行 → 内容行缩进 2（对应 --sp-2）
- 分隔线用 ── 全宽（对应 hair border）
"""

from __future__ import annotations

from rich.style import Style
from rich.text import Text

# ---- 语义色（与 Reasonix tokens.css 的命名对齐）--------------------------
ACCENT = "bold color(214)"       # 琥珀：需要你注意
NET = "color(75)"                # 蓝：自持运行
DELEG = "color(80)"              # 青：委派
OK = "color(114)"                # 绿：完成
ERR = "color(203)"               # 红：错误
WARN = "color(216)"              # 暖色警告
DIM = "dim"                      # 辅助
BOLD = "bold"

# ---- 工具状态图标（对齐 ToolCard 的 STATUS 表）----------------------------
TOOL_STATUS = {
    "running": ("▸", NET),
    "done": ("✓", OK),
    "error": ("✗", ERR),
}

# ---- 回合分隔线（对齐 turn 卡片的 label 形态）-----------------------------
TURN_SEP = "─" * 48
TURN_END_SEP = "·" + "─" * 46 + "·"

# ---- 横幅 ----------------------------------------------------------------
BANNER = r"""
 ██████  ███████ ███████ ██████   █████   ██████ ██   ██
 ██   ██ ██      ██      ██   ██ ██   ██ ██      ██   ██
 ██████  █████   █████   ██████  ███████ ██      ███████
 ██   ██ ██      ██      ██   ██ ██   ██ ██      ██   ██
 ██████  ███████ ██      ██   ██ ██   ██  ██████ ██   ██
"""


def turn_header(turn_id: str) -> Text:
    """回合开始的分隔行。"""
    text = Text()
    text.append(TURN_SEP, style=DIM)
    text.append(f" turn {turn_id[:8]} ", style=f"{DIM} reverse")
    return text


def turn_footer(outcome: str, duration_ms: int, usage: dict[str, int] | None = None) -> Text:
    """回合收尾：结果 + 耗时 + token 用量（对齐 MeterRail 的摘要行）。"""
    text = Text()
    style = {"completed": OK, "failed": ERR, "cancelled": WARN}.get(outcome, DIM)
    icon = {"completed": "✓", "failed": "✗", "cancelled": "⊘"}.get(outcome, "·")
    text.append(f"{icon} {outcome}", style=f"{style} bold")
    text.append(f" · {duration_ms}ms", style=DIM)
    if usage:
        text.append(
            f" · {usage.get('inputTokens', '?')}→{usage.get('outputTokens', '?')} tok",
            style=DIM,
        )
    return text


def tool_line(tool: str, status: str, output: str | None = None, max_output: int = 120) -> Text:
    """工具行：图标 + 名称 + 状态 + 输出预览。"""
    icon, color = TOOL_STATUS.get(status, ("·", DIM))
    text = Text()
    text.append(f"  {icon} ", style=color)
    text.append(tool, style=BOLD)
    text.append(f" {status}", style=color)
    if output:
        first_line = output.strip().splitlines()[0][:max_output] if output.strip() else ""
        if first_line:
            text.append(f"  {first_line}", style=DIM)
    return text


def approval_header(tool: str, subject: str) -> Text:
    """审批卡标题行：对齐 ApprovalCard 的「需要审批 | tool | subject」。"""
    text = Text()
    text.append("  ⚠ ", style=ACCENT)
    text.append("需要审批", style=ACCENT)
    text.append(f"  {tool}", style=BOLD)
    text.append(f"  {subject}", style=NET)
    return text


def notice_bar(text_content: str, level: str) -> Text:
    """提示行：error 红条，info 暗条。"""
    text = Text()
    if level == "error":
        text.append("  ✗ ", style=ERR)
        text.append(text_content, style=ERR)
    else:
        text.append("  · ", style=DIM)
        text.append(text_content, style=DIM)
    return text


def compaction_line(phase: str, trigger: str) -> Text:
    """压缩进度行：对齐 CompactionCard 的 started/progress/done。"""
    icons = {"started": "▶", "done": "✓"}
    icon = icons.get(phase.split("_")[-1], "·")
    text = Text()
    text.append(f"  {icon} ", style=DELEG)
    text.append("上下文压缩", style=DELEG)
    text.append(f" · {trigger}", style=DIM)
    return text


def status_bar(profile_name: str, model: str | None = None, busy: bool = False) -> Text:
    """底部状态条（对齐 Reasonix Chrome 的右侧 status span）。"""
    text = Text()
    text.append(f" {profile_name}", style=f"{NET} bold")
    if model:
        text.append(f" · {model}", style=DIM)
    text.append(" · " + ("回合进行中" if busy else "空闲"), style=WARN if busy else OK)
    return text
