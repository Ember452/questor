"""终端界面文案：中文一等公民的唯一落点。

终端包内其余模块不得出现中文字面量（`tests/unit/bootstrap/hosts/terminal/`
的文案集中度用例守着）；命令名、工具名、模型名等标识符保持原样，不进这里。
"""

from __future__ import annotations

# ---- 未实现徽标（plan03 §5）--------------------------------------------
BADGE_MARK = "⊘"
BADGE_FORMAT = "{mark} 未实现 · {gap_id} {name}"
GAPS_LEAD = "  未实现的入口："

# ---- 输入框（形态取自 Reasonix `tui/chrome.go` 的提示符）------------------
PROMPT = "❯ "
CONTINUATION = "… "

# ---- 缺数据占位（FooterVM 的可选字段）-----------------------------------
PLACEHOLDER = "—"

# ---- 空态提示（对齐 Reasonix Hero 的一句话）-----------------------------
EMPTY_STATE_LINES = (
    "输入一句话开始；/ 查指令，:model 等打开面板。",
    "↑↓ 翻历史 · Tab 补全 · Ctrl-C 中止回合 · Ctrl-D 退出",
)

# ---- 卡片内的补充文案（主题里的固定文案仍归 terminal_theme）-------------
STREAM_RESET = "数据流已重置，正在重取历史"
UNSUPPORTED_LEAD = "降级"
IMAGE_BLOCK = "[图片 {media_type}]"
TOOL_USE_BLOCK = "工具 call {tool_use_id} · {name}"
APPROVAL_CHOICES = "  y 允许 · N 拒绝（回车默认拒绝）"
APPROVAL_MODE_HINT = "  换档：:mode 或 /permissions <default|plan|full_auto>"
ASK_HINT = "  输入回答后回车（空输入视为未回答）"
DIFF_TRUNCATED = "补丁过长，已截断（完整内容见编辑工具输出）"

# ---- 回合控制 -----------------------------------------------------------
QUEUED = "  … 已排队（回合结束后自动开始）"
CANCEL_SENT = "  已请求取消（Ctrl-C）"

# ---- 时限与降级 ---------------------------------------------------------
APPROVAL_TIMEOUT = "  已超时，按拒绝处理"
ASK_TIMEOUT = "  已超时，按未回答处理"
APPROVAL_INTERRUPT = "  已中断，按拒绝处理"
ASK_INTERRUPT = "  已中断，按未回答处理"
RENDER_FAILED = "  降级 {item} · 渲染失败：{detail}"


def render_failed(item: str, detail: str) -> str:
    """单帧渲染异常时的降级行（可见、不静默、不拖垮事件消费）。"""

    return RENDER_FAILED.format(item=item, detail=detail)


# ---- 面板（alt-screen 与编号回退共用）------------------------------------
PANEL_HINT = "  j/k ↑↓ 选择 · Enter 确认 · / 搜索 · Esc 退出"
PANEL_GROUP = "  ── {group} ──"
PANEL_CHOICE_PROMPT = "  选择序号（/ 搜索 · 空=取消）："
PANEL_SEARCH_PROMPT = "  搜索（回车应用 · 空=清过滤 · Ctrl-C 保持）："
PANEL_EMPTY = "  这个面板现在是空的"
PANEL_UNAVAILABLE = "  面板取不到数据（{reason}）"
