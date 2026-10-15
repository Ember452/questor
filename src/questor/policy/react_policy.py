"""L4 进程内 ReAct 策略，实现 ``PolicyPort``（design/05；P1 T11）。

读只读的 ``PolicyView``、每 turn 返回恰好一个不可信意图：若最新 assistant 消息里有
一条未应答的 tool_use，就提议调它；否则建议收尾。它不拥有执行/权限/持久化（05 §0）。
P1 用单个硬编码策略；注册表/热替换/AB 归 P9（这里只留 ``id``/``fingerprint`` 位，ADR-0009）。
"""

from __future__ import annotations

from questor.contracts.common import JsonObject
from questor.contracts.policy import PolicyIntent, PolicyPort, PolicyView, ProposeToolCall, SuggestFinish
from questor.contracts.state_schema import OPEN_TOOL_CALL_STATUSES, Role


class ReActPolicy(PolicyPort):
    """最小 ReAct：单步地“有未闭合工具就调它，否则收尾”。"""

    id = "react"
    fingerprint = "react:1"

    def propose_action(self, view: PolicyView) -> PolicyIntent:
        """读视图→出一个单步意图；内核执行前会再校验（视为不可信输入）。"""
        # 已闭合（非 pending/running）的调用 id 集合，用来判断哪条 tool_use 还没被应答。
        answered = {c.tool_call_id for c in view.tool_results if c.status not in OPEN_TOOL_CALL_STATUSES}
        last_assistant = next((m for m in reversed(view.context) if m.role is Role.ASSISTANT), None)
        if last_assistant is None:
            return SuggestFinish(final_text=None)

        for block in last_assistant.content:
            if block.type == "tool_use" and block.tool_use_id and block.tool_use_id not in answered:
                args: JsonObject = dict(block.input or {})
                return ProposeToolCall(name=block.name or "", args=args, tool_call_id=block.tool_use_id)

        text = "".join(b.text or "" for b in last_assistant.content if b.type == "text")
        return SuggestFinish(final_text=text or None)


__all__ = ["ReActPolicy"]
