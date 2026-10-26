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

# ---- 横向 ----------------------------------------------------------------
# 首屏只留一行品牌：此前那段 ASCII art 拼不出产品名（逐列解析只得
# "R E F P A C H"），而且在窄屏/双宽字形下会断裂。品牌靠字形 + 颜色，不靠方块。
BANNER = "✳ QuestorHarness"


def turn_header(turn_id: str = "") -> Text:
    """回合开始的分隔行。

    `turn_id` 不再上屏：UUID 前 8 位对用户零信息，而每回合多两行噪声会
    把 24 行终端的可用高度吃掉。参数保留只为兼容调用方与既有快照。
    """

    text = Text()
    text.append(TURN_SEP, style=DIM)
    return text


def turn_footer(label: str, duration_ms: int, usage: dict[str, int] | None = None) -> Text:
    """回合收尾：结果 + 耗时（秒）+ token 用量。"""

    text = Text()
    style = {"完成": OK, "失败": ERR, "已取消": WARN}.get(label, DIM)
    icon = {"完成": "✓", "失败": "✗", "已取消": "⊘"}.get(label, "·")
    text.append(f"{icon} {label}", style=f"{style} bold")
    text.append(f" · {duration_ms / 1000:.1f}s", style=DIM)
    if usage:
        text.append(
            f" · {usage.get('inputTokens', '?')}→{usage.get('outputTokens', '?')} tok",
            style=DIM,
        )
    return text


def tool_card(tool: str, output: str | None, *, is_error: bool) -> Text:
    """工具卡（两行节奏）：标题行 `● tool`，收口行 `⎿ 结果摘要`。

    与 Reasonix `termrender/toolcard.go` / DeepCode `● Read + ⎿` 同一语法：
    状态色点在行首，结果用 `dim` 退后——结构靠缩进与颜色，不靠边框
    （边框会把 80 列吃掉 4 列，并且折行时断开）。
    """

    icon, color = TOOL_STATUS.get("error" if is_error else "done", ("·", DIM))
    head = Text()
    head.append(f"  {icon} ", style=color)
    head.append(tool, style=BOLD)
    first = ""
    if output and output.strip():
        first = output.strip().splitlines()[0][:120]
    if first:
        head.append("\n  ⎿ ", style=DIM)
        head.append(first, style=DIM)
    return head


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


# ---- 清单卡（对齐 Reasonix todos.go 的勾选行）-----------------------------
TODO_CHECKED = "✓"
TODO_OPEN = "○"


def status_bar(profile_name: str, model: str | None = None, busy: bool = False) -> Text:
    """底部状态条（对齐 Reasonix Chrome 的右侧 status span）。"""
    text = Text()
    text.append(f" {profile_name}", style=f"{NET} bold")
    if model:
        text.append(f" · {model}", style=DIM)
    text.append(" · " + ("回合进行中" if busy else "空闲"), style=WARN if busy else OK)
    return text


def todo_card(title: str, rows: list[tuple[str, bool]]) -> Text:
    """清单卡：标题行 + 逐项勾选态（终端的 todo 面板就是这个图元）。"""
    text = Text()
    text.append(f"  {title}", style=f"{BOLD}")
    if not rows:
        text.append("  （空）", style=DIM)
        return text
    done = sum(1 for _, checked in rows if checked)
    text.append(f"  {done}/{len(rows)}", style=DIM)
    for label, checked in rows:
        text.append("\n")
        if checked:
            text.append(f"  {TODO_CHECKED} ", style=OK)
            text.append(label, style=DIM)
        else:
            text.append(f"  {TODO_OPEN} ", style=ACCENT)
            text.append(label)
    return text
