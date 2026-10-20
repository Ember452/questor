"""内置 HITL 提问工具：``ask_user``（§13 B15「可问」；复用审批生命周期，不新建第二条通道）。

设计取舍（对着代码事实，不是对着愿望）：本仓**已经有**一条人机确认通道——权限评估出 ASK →
`RequestApproval` durable 请求 → inbox 或超时 → `ResolveApproval`。所以"问一句"不需要新代码路径：
把问题放进工具参数，让 `approval_mode="prompt"` 把它抬成一次审批请求就是问用户。

* `permission_policy._apply_approval_mode`（L2 已实现）把 ALLOW 收紧为 ASK，`floor_applied
  ="approval-mode"`；本工具因此**每次调用都要人答一次**，与 MCP 的"只收紧不放宽"同一条规则。
* 三种结局都是既有事实，不需要新事件：允许 → 工具被执行（走到 execute 本身就是"准了"）；
  拒绝 → `tool_completed(status="denied")`，模型看见问题被拒；超时 → `ExpireApproval` 那条路径。
* **自由文本答案当前没有通道**：`ResolveApproval` 只带 allow/deny（加可选字段是 additive 契约变更，
  留给后续刀，见 ADR-0059）。所以本工具的语义是"要不要按这个问题/选项继续"，不是"用户打字回答"。
  工具不假装能拿到回答——这是它的硬边界。
"""

from __future__ import annotations

from questor.contracts.common import JsonObject
from questor.contracts.tool import Capability, Risk, Tool, ToolContext, ToolResult, ToolSpec

#: 问题与选项的硬上限（一次提问只占一屏，超长是提示词 bug，不是"内容多"）。
MAX_QUESTION_CHARS = 400
MAX_OPTIONS = 6
MAX_OPTION_CHARS = 80

_SPEC = ToolSpec(
    name="ask_user",
    description=(
        "Ask the user one question and wait for their assent before continuing. "
        "The question is shown as an approval prompt: allowing continues, denying is the user refusing. "
        "Use when a single clarification is cheaper than a wrong multi-step attempt; never for free-form chat."
    ),
    params={
        "type": "object",
        "properties": {
            "question": {"type": "string", "minLength": 1, "maxLength": MAX_QUESTION_CHARS},
            "options": {
                "type": "array",
                "maxItems": MAX_OPTIONS,
                "items": {"type": "string", "minLength": 1, "maxLength": MAX_OPTION_CHARS},
            },
            "why": {"type": "string", "maxLength": MAX_QUESTION_CHARS, "description": "what depends on the answer"},
        },
        "required": ["question"],
        "additionalProperties": False,
    },
    capability=Capability.READONLY,
    risk=Risk.LOW,
    read_only=True,
    timeout_s=30,
    # 工具策略位：权限评估本来会 ALLOW，这一位把它抬成 ASK（只收紧不放宽，A 类不变量）。
    approval_mode="prompt",
)


class AskUserTool(Tool):
    """把问题交给审批面；execute 只在用户**准许后**运行，因此结果里只陈述"已确认"。"""

    spec = _SPEC

    def available(self) -> bool:
        return True

    async def execute(self, args: JsonObject, ctx: ToolContext) -> ToolResult:
        """校验参数 → 有界回执（不给模型任何"用户写了什么"的假象）。"""
        question = args.get("question")
        if not isinstance(question, str) or not question.strip():
            return ToolResult(status="error", result="ask_user requires a non-empty question")
        if len(question) > MAX_QUESTION_CHARS:
            return ToolResult(status="error", result=f"ask_user question exceeds {MAX_QUESTION_CHARS} chars")
        raw_options = args.get("options") or []
        if not isinstance(raw_options, list):
            return ToolResult(status="error", result="ask_user options must be an array of strings")
        options = [option.strip() for option in raw_options if isinstance(option, str) and option.strip()][:MAX_OPTIONS]
        if ctx.is_cancelled():
            return ToolResult(status="error", result="cancelled")

        why = args.get("why")
        lines = [f"user was asked and allowed: {question.strip()}"]
        if options:
            lines.append("options offered: " + " | ".join(options))
        if isinstance(why, str) and why.strip():
            lines.append(f"why it was asked: {why.strip()}")
        lines.append(
            "note: this channel carries assent only (allow / deny / expired); the user's free-text answer is not available here."
        )
        # display 给桌面卡片（人看的一版），result 给模型（有界、含"别把它当自由回答"的提醒）。
        return ToolResult(status="success", result="\n".join(lines), display=f"✓ asked: {question.strip()}")


__all__ = ["AskUserTool", "MAX_OPTIONS", "MAX_OPTION_CHARS", "MAX_QUESTION_CHARS"]
