"""终端界面文案：中文一等公民的唯一落点。

终端包内其余模块不得出现中文字面量（`tests/unit/bootstrap/hosts/terminal/`
的文案集中度用例守着）；命令名、工具名、模型名等标识符保持原样，不进这里。
"""

from __future__ import annotations

import sys

# ---- 品牌（首屏一句话；ASCII art 已退役：它拼不出产品名，还会在窄屏断裂）----
BRAND_TAGLINE = "本地优先的编码 Agent"
BRAND_HINT = "/ 查指令 · : 打开面板 · /help 看全部"

# ---- 未实现徽标（plan03 §5）--------------------------------------------
BADGE_MARK = "⊘"
BADGE_FORMAT = "{mark} 未实现 · {gap_id} {name}"
GAPS_LEAD = "  未实现的入口："

# ---- 输入框（形态取自 Reasonix `tui/chrome.go` 的提示符）------------------
PROMPT = "❯ "
PROMPT_FALLBACK = "> "

# ---- 缺数据占位（FooterVM 的可选字段）-----------------------------------
PLACEHOLDER = "—"

# ---- 空态提示（对齐 Reasonix Hero 的一句话）-----------------------------
EMPTY_STATE_LINES = (
    "说一句话开始；" + BRAND_HINT,
    "↑↓ 翻历史 · Tab 补全 · Ctrl-C 中止回合 · Ctrl-D 退出",
)

# ---- 回合进行中的静默期（模型吐第一个字节之前的唯一反馈）----------------
THINKING = "⋯ 思考中…（Ctrl-C 中止）"

# ---- 卡片内的补充文案（主题里的固定文案仍归 terminal_theme）-------------
STREAM_RESET = "数据流已重置，正在重取历史"
UNSUPPORTED_LEAD = "降级"
IMAGE_BLOCK = "[图片 {media_type}]"
APPROVAL_CHOICES = "  y 允许 · n 拒绝（回车默认拒绝）"
APPROVAL_MODE_HINT = "  换档：:mode 或 /permissions <default|plan|full_auto>"
APPROVAL_UNKNOWN = "  只认 y / n（回车默认拒绝）"
ASK_HINT = "  输入回答后回车；有编号时可直接打序号（空输入视为未回答）"
DIFF_TRUNCATED = "补丁过长，已截断（完整内容见编辑工具输出）"

# ---- 指令面（未知指令不得漏给模型）--------------------------------------
UNKNOWN_COMMAND = "  未知指令 {name} · 未发送给模型 · Tab 补全，:help 看全部指令"
COMMAND_LIST_LEAD = "  可用指令（前 {shown} 条；:help 面板里搜）"
NO_MATCH_HINT = "  没有匹配的指令（继续打字以缩小范围）"
BUSY_REFUSED = "  回合进行中：先 Ctrl-C 中止，或等它跑完"

# ---- 补全菜单（Reasonix 风格；由底部工具栏渲染，`›` 为选中行）----------
MENU_HINT_SLASH = "  ↑↓ 选择 · Tab/Enter 补全 · Esc 关闭"
MENU_HINT_FILE = "  ↑↓ 选择 · Tab/Enter 补全 · @ 引用文件 · Esc 关闭"

# ---- 会话恢复与回合结果（主题只管图标与颜色，文案在这里）--------------
REPLAY_LEAD = "  已恢复上次会话（{shown} 块），可以接着聊"

OUTCOME_LABELS = {
    "completed": "完成",
    "failed": "失败",
    "cancelled": "已取消",
}

# ---- 回合控制 -----------------------------------------------------------
QUEUED = "  … 已排队（回合结束后自动开始）"
CANCEL_SENT = "  已请求取消（Ctrl-C）"
CTRL_C_QUIT_HINT = "  再按一次 Ctrl-C 退出（空闲时两下退出；忙时先取消回合）"
SUBMIT_REFUSED = "  提交被拒（{detail}）"

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


def prompt_marker(encoding: str | None = None) -> str:
    """接台能编码就返回 `❯ `，否则退回 `> `（plan03 波 F：cp936 控制台实跑撞过）。

    不传 `encoding` 时看当前 stdout 的编码（管道/重定向下就是宿主编码）。
    `input()` / `PromptSession.prompt()` 会先把提示符写到 stdout，
    字面量无法编码时整个 REPL 直接抛 UnicodeEncodeError，所以降级必须在传入前完成。
    """

    target = encoding or getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        PROMPT.encode(target)
    except (LookupError, UnicodeEncodeError):
        return PROMPT_FALLBACK
    return PROMPT
