"""StreamEvent → wire 帧编码。

本模块只做映射：不分配 seq（那是 broadcaster 的职责），也不做背压。
未知事件类型直接抛错——静默丢弃会让前端少一类帧却毫无告警。
"""

from __future__ import annotations

from collections import deque
from typing import Any, Final

from questorharness.contracts.domain.events import (
    AssistantTextDelta,
    AssistantTurnComplete,
    CompactProgressEvent,
    ErrorEvent,
    StatusEvent,
    StreamEvent,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)
from questorharness.contracts.usage import UsageSnapshot

Frame = dict[str, Any]

# 事件 → 帧种类的全量映射（kind 覆盖守卫读它）。
STREAM_EVENT_TO_KINDS: Final[dict[type[object], tuple[str, ...]]] = {
    AssistantTextDelta: ("text",),
    AssistantTurnComplete: ("message",),
    ToolExecutionStarted: ("tool_dispatch",),
    ToolExecutionCompleted: ("tool_result",),
    ErrorEvent: ("notice",),
    StatusEvent: ("notice",),
    CompactProgressEvent: ("compaction_started", "compaction_progress", "compaction_done"),
}

_START_PHASE: Final[str] = "compact_start"
_END_PHASE: Final[str] = "compact_end"
_FAILED_PHASE: Final[str] = "compact_failed"


def usage_frame(usage: UsageSnapshot) -> Frame:
    """把 UsageSnapshot 转成 wire 形状。"""
    return {"inputTokens": usage.input_tokens, "outputTokens": usage.output_tokens}


# ---- 宿主直出的 5 帧：唯一构造函数 ------------------------------------
def turn_started_frame(*, turn_id: str, index: int, via: str) -> Frame:
    """提交到达：回合开始。"""
    return {"kind": "turn_started", "turnId": turn_id, "index": index, "via": via}


def turn_done_frame(
    *,
    turn_id: str,
    cancelled: bool,
    outcome: str,
    duration_ms: int,
    checkpoint_turn: bool = False,
    usage: UsageSnapshot | None = None,
) -> Frame:
    """回合结束；`checkpointTurn` 在引擎 P1 落地前恒为 false。"""
    frame: Frame = {
        "kind": "turn_done",
        "turnId": turn_id,
        "cancelled": cancelled,
        "outcome": outcome,
        "durationMs": duration_ms,
        "checkpointTurn": checkpoint_turn,
    }
    if usage is not None:
        frame["usage"] = usage_frame(usage)
    return frame


def approval_request_frame(*, prompt_id: str, tool: str, subject: str) -> Frame:
    """权限审批请求；客户端用 id 回 `/approve`。"""
    return {"kind": "approval_request", "id": prompt_id, "tool": tool, "subject": subject}


def ask_request_frame(*, prompt_id: str, question: str) -> Frame:
    """工具提问；客户端用 id 回 `/ask`。"""
    return {"kind": "ask_request", "id": prompt_id, "question": question}


def stream_reset_frame(*, reason: str, watermark: int) -> Frame:
    """重放窗口越界；客户端应重取 `/history`。"""
    return {"kind": "stream_reset", "reason": reason, "seq": watermark}


def _blocks(message: Any) -> list[Frame]:
    """把 ConversationMessage 的内容块展平；不认识的块类型直接报错。"""
    blocks: list[Frame] = []
    for block in getattr(message, "content", []):
        kind = getattr(block, "type", None)
        if kind == "text":
            blocks.append({"type": "text", "text": block.text})
        elif kind == "image":
            blocks.append({"type": "image", "mediaType": block.media_type})
        elif kind == "tool_use":
            blocks.append({"type": "tool_use", "id": block.id, "name": block.name})
        elif kind == "tool_result":
            blocks.append(
                {
                    "type": "tool_result",
                    "toolUseId": block.tool_use_id,
                    "content": block.content,
                    "isError": block.is_error,
                }
            )
        else:
            raise ValueError(f"unsupported content block: {kind!r}")
    return blocks


class WireEncoder:
    """有状态编码器：持有当前 turn 的上下文与工具调用配对表。"""

    def __init__(self) -> None:
        self.turn_id: str = ""
        self.index: int = 0
        self.via: str = "studio"
        self.last_usage: UsageSnapshot | None = None
        self._tool_calls: dict[str, deque[str]] = {}
        self._tool_seq = 0

    def start_turn(self, *, turn_id: str, index: int, via: str) -> Frame:
        """生成 turn_started 帧并重置工具配对表。"""
        self.turn_id = turn_id
        self.index = index
        self.via = via
        self._tool_calls.clear()
        self._tool_seq = 0
        return turn_started_frame(turn_id=turn_id, index=index, via=via)

    def _mint_tool_call(self, tool_name: str) -> str:
        """为一次工具调用铸造关联 id（引擎事件不携带 id）。

        id 必须可复现：用 turn 内单调计数，不能用内存地址（前者进黄金帧，
        后者会随进程变化）。
        """
        self._tool_seq += 1
        call_id = f"{tool_name}-{self.index}-{self._tool_seq}"
        self._tool_calls.setdefault(tool_name, deque()).append(call_id)
        return call_id

    def _take_tool_call(self, tool_name: str) -> str:
        """取出与 Completed 配对的 id；配对缺失时退化为新号。"""
        pending = self._tool_calls.get(tool_name)
        if pending:
            return pending.popleft()
        return self._mint_tool_call(tool_name)

    def encode(self, event: StreamEvent) -> list[Frame]:
        """把单个 StreamEvent 编码成 0..n 个帧（顺序稳定）。"""
        if isinstance(event, AssistantTextDelta):
            return [{"kind": "text", "text": event.text}]
        if isinstance(event, AssistantTurnComplete):
            self.last_usage = event.usage
            return [
                {
                    "kind": "message",
                    "blocks": _blocks(event.message),
                    "usage": usage_frame(event.usage),
                }
            ]
        if isinstance(event, ToolExecutionStarted):
            return [
                {
                    "kind": "tool_dispatch",
                    "toolCallId": self._mint_tool_call(event.tool_name),
                    "tool": event.tool_name,
                }
            ]
        if isinstance(event, ToolExecutionCompleted):
            return [
                {
                    "kind": "tool_result",
                    "toolCallId": self._take_tool_call(event.tool_name),
                    "tool": event.tool_name,
                    "output": event.output,
                    "isError": event.is_error,
                }
            ]
        if isinstance(event, ErrorEvent):
            return [{"kind": "notice", "level": "error", "text": event.message}]
        if isinstance(event, StatusEvent):
            return [{"kind": "notice", "level": "info", "text": event.message}]
        if isinstance(event, CompactProgressEvent):
            return [self._compact(event)]
        raise ValueError(f"unsupported stream event: {type(event).__name__}")

    def _compact(self, event: CompactProgressEvent) -> Frame:
        """9 个相位归并成三帧。"""
        if event.phase == _START_PHASE:
            return {"kind": "compaction_started", "trigger": event.trigger}
        if event.phase in (_END_PHASE, _FAILED_PHASE):
            return {
                "kind": "compaction_done",
                "trigger": event.trigger,
                "ok": event.phase == _END_PHASE,
            }
        frame: Frame = {"kind": "compaction_progress", "phase": event.phase}
        if event.attempt is not None:
            frame["attempt"] = event.attempt
        if event.message is not None:
            frame["message"] = event.message
        return frame
