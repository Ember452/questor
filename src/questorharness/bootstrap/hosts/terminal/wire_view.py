"""wire 帧 → 视图模型（VM）。

终端只认这一层：卡片/输入/覆盖层不得直接读 raw frame（plan03 §2.2 顺序约束）。
两条降级只有在渲染层可见时才算"没丢帧"：

* 未登记的 kind（未来服务端先上）→ `UnsupportedItem`；
* 已登记但字段缺失/类型不符（旧服务端、半截帧）→ 同样降级，并带上原因。

VM 全部不可变，且不持有原始 dict —— 终端不因此获得第二份状态源。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, TypeAlias

KNOWN_KINDS: Final[frozenset[str]] = frozenset(
    {
        "turn_started",
        "text",
        "message",
        "tool_dispatch",
        "tool_result",
        "notice",
        "approval_request",
        "ask_request",
        "compaction_started",
        "compaction_progress",
        "compaction_done",
        "turn_done",
        "stream_reset",
        "todos",
    }
)


class _Malformed(ValueError):
    """帧已登记但字段不合约：交给 `view_of` 降级，不让渲染层崩。"""


# ---- 基础值对象 ---------------------------------------------------------


@dataclass(frozen=True)
class UsageVM:
    input_tokens: int
    output_tokens: int
    cost_usd: float | None = None
    context_window: int | None = None
    context_used: int | None = None
    cached_tokens: int | None = None


@dataclass(frozen=True)
class TextBlockVM:
    text: str


@dataclass(frozen=True)
class ImageBlockVM:
    media_type: str


@dataclass(frozen=True)
class ToolUseBlockVM:
    tool_use_id: str
    name: str


@dataclass(frozen=True)
class ToolResultBlockVM:
    tool_use_id: str
    content: str
    is_error: bool


BlockVM: TypeAlias = TextBlockVM | ImageBlockVM | ToolUseBlockVM | ToolResultBlockVM


# ---- 帧对应的视图模型 ---------------------------------------------------


@dataclass(frozen=True)
class TurnStartedItem:
    turn_id: str
    index: int
    via: str


@dataclass(frozen=True)
class TextItem:
    text: str


@dataclass(frozen=True)
class MessageItem:
    blocks: tuple[BlockVM, ...]
    usage: UsageVM | None


@dataclass(frozen=True)
class ToolDispatchItem:
    tool_call_id: str
    tool: str


@dataclass(frozen=True)
class ToolResultItem:
    tool_call_id: str
    tool: str
    output: str
    is_error: bool


@dataclass(frozen=True)
class NoticeItem:
    level: str
    text: str


@dataclass(frozen=True)
class ApprovalItem:
    prompt_id: str
    tool: str
    subject: str
    detail: str
    patch: str | None = None
    added: int | None = None
    removed: int | None = None


@dataclass(frozen=True)
class AskItem:
    prompt_id: str
    question: str
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompactionStartedItem:
    trigger: str


@dataclass(frozen=True)
class CompactionProgressItem:
    phase: str
    attempt: int
    message: str


@dataclass(frozen=True)
class CompactionDoneItem:
    trigger: str
    ok: bool


@dataclass(frozen=True)
class TurnDoneItem:
    turn_id: str
    cancelled: bool
    outcome: str
    duration_ms: int
    checkpoint_turn: bool
    usage: UsageVM | None


@dataclass(frozen=True)
class StreamResetItem:
    reason: str


@dataclass(frozen=True)
class TodoRow:
    text: str
    checked: bool


@dataclass(frozen=True)
class TodosItem:
    """清单快照（W-D4）：serve 在 todo_write 成功后从清单文件读出。"""

    path: str
    rows: tuple[TodoRow, ...]


@dataclass(frozen=True)
class UnsupportedItem:
    """未登记 kind 或坏帧：渲染成一行可见的降级提示，不丢、不崩。"""

    kind: str
    reason: str


Item: TypeAlias = (
    TurnStartedItem
    | TextItem
    | MessageItem
    | ToolDispatchItem
    | ToolResultItem
    | NoticeItem
    | ApprovalItem
    | AskItem
    | CompactionStartedItem
    | CompactionProgressItem
    | CompactionDoneItem
    | TurnDoneItem
    | StreamResetItem
    | TodosItem
    | UnsupportedItem
)


# ---- 字段读取（缺字段/错类型 → _Malformed）------------------------------


def _str(frame: Mapping[str, Any], key: str, *, default: str | None = None) -> str:
    value = frame.get(key, default)
    if isinstance(value, str):
        return value
    if default is not None:
        return default
    raise _Malformed(f"{key} 缺失或不是字符串")


def _int(frame: Mapping[str, Any], key: str, *, default: int | None = None) -> int:
    value = frame.get(key, default)
    if isinstance(value, bool):
        raise _Malformed(f"{key} 是布尔值，期望整数")
    if isinstance(value, int):
        return value
    if default is not None:
        return default
    raise _Malformed(f"{key} 缺失或不是整数")


def _bool(frame: Mapping[str, Any], key: str, *, default: bool = False) -> bool:
    value = frame.get(key, default)
    if isinstance(value, bool):
        return value
    if default is not None:
        return default
    raise _Malformed(f"{key} 缺失或不是布尔值")


def _usage(frame: Mapping[str, Any]) -> UsageVM | None:
    raw = frame.get("usage")
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise _Malformed("usage 不是对象")
    cost = raw.get("costUsd")
    return UsageVM(
        input_tokens=_int(raw, "inputTokens", default=0),
        output_tokens=_int(raw, "outputTokens", default=0),
        cost_usd=float(cost) if isinstance(cost, (int, float)) else None,
        context_window=_int(raw, "contextWindow", default=0) or None,
        context_used=_int(raw, "contextUsed", default=0) or None,
        cached_tokens=_int(raw, "cachedTokens", default=0) or None,
    )


def _block(raw: Any) -> BlockVM:
    if not isinstance(raw, Mapping):
        raise _Malformed("content block 不是对象")
    kind = raw.get("type")
    if kind == "text":
        return TextBlockVM(text=_str(raw, "text", default=""))
    if kind == "image":
        return ImageBlockVM(media_type=_str(raw, "mediaType", default=""))
    if kind == "tool_use":
        return ToolUseBlockVM(
            tool_use_id=_str(raw, "id", default=""), name=_str(raw, "name", default="")
        )
    if kind == "tool_result":
        return ToolResultBlockVM(
            tool_use_id=_str(raw, "toolUseId", default=""),
            content=_str(raw, "content", default=""),
            is_error=_bool(raw, "isError"),
        )
    # 未知块类型：可见降级为文本，不整帧丢弃（与 routes._history_blocks 同口径）。
    return TextBlockVM(text=f"[unsupported block] {kind}")


def _blocks(frame: Mapping[str, Any]) -> tuple[BlockVM, ...]:
    raw = frame.get("blocks")
    if raw is None:
        return ()
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise _Malformed("blocks 不是数组")
    return tuple(_block(item) for item in raw)


# ---- 投影表 -------------------------------------------------------------


def _turn_started(frame: Mapping[str, Any]) -> Item:
    return TurnStartedItem(
        turn_id=_str(frame, "turnId"),
        index=_int(frame, "index"),
        via=_str(frame, "via", default="cli"),
    )


def _text(frame: Mapping[str, Any]) -> Item:
    return TextItem(text=_str(frame, "text"))


def _message(frame: Mapping[str, Any]) -> Item:
    return MessageItem(blocks=_blocks(frame), usage=_usage(frame))


def _tool_dispatch(frame: Mapping[str, Any]) -> Item:
    return ToolDispatchItem(
        tool_call_id=_str(frame, "toolCallId"), tool=_str(frame, "tool")
    )


def _tool_result(frame: Mapping[str, Any]) -> Item:
    return ToolResultItem(
        tool_call_id=_str(frame, "toolCallId"),
        tool=_str(frame, "tool"),
        output=_str(frame, "output", default=""),
        is_error=_bool(frame, "isError"),
    )


def _notice(frame: Mapping[str, Any]) -> Item:
    return NoticeItem(level=_str(frame, "level", default="info"), text=_str(frame, "text"))


def _approval(frame: Mapping[str, Any]) -> Item:
    return ApprovalItem(
        prompt_id=_str(frame, "id"),
        tool=_str(frame, "tool"),
        subject=_str(frame, "subject"),
        detail=_str(frame, "detail", default=""),
        patch=_str(frame, "patch", default="") or None,
        added=_int(frame, "added", default=-1) if "added" in frame else None,
        removed=_int(frame, "removed", default=-1) if "removed" in frame else None,
    )


def _ask(frame: Mapping[str, Any]) -> Item:
    raw = frame.get("options")
    if raw is None:
        raw = []
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise _Malformed("options 不是数组")
    return AskItem(
        prompt_id=_str(frame, "id"),
        question=_str(frame, "question"),
        options=tuple(str(option) for option in raw),
    )


def _compaction_started(frame: Mapping[str, Any]) -> Item:
    return CompactionStartedItem(trigger=_str(frame, "trigger", default="auto"))


def _compaction_progress(frame: Mapping[str, Any]) -> Item:
    return CompactionProgressItem(
        phase=_str(frame, "phase"),
        attempt=_int(frame, "attempt", default=1),
        message=_str(frame, "message", default=""),
    )


def _compaction_done(frame: Mapping[str, Any]) -> Item:
    return CompactionDoneItem(
        trigger=_str(frame, "trigger", default="auto"), ok=_bool(frame, "ok", default=True)
    )


def _turn_done(frame: Mapping[str, Any]) -> Item:
    return TurnDoneItem(
        turn_id=_str(frame, "turnId", default=""),
        cancelled=_bool(frame, "cancelled"),
        outcome=_str(frame, "outcome"),
        duration_ms=_int(frame, "durationMs", default=0),
        checkpoint_turn=_bool(frame, "checkpointTurn"),
        usage=_usage(frame),
    )


def _stream_reset(frame: Mapping[str, Any]) -> Item:
    return StreamResetItem(reason=_str(frame, "reason", default="unknown"))


def _todos(frame: Mapping[str, Any]) -> Item:
    raw = frame.get("items")
    if raw is None:
        raw = []
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise _Malformed("items 不是数组")
    rows: list[TodoRow] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            raise _Malformed("清单行不是对象")
        rows.append(
            TodoRow(text=_str(entry, "text", default=""), checked=_bool(entry, "checked"))
        )
    return TodosItem(path=_str(frame, "path", default="TODO.md"), rows=tuple(rows))


_PROJECTIONS: Final[dict[str, Callable[[Mapping[str, Any]], Item]]] = {
    "turn_started": _turn_started,
    "text": _text,
    "message": _message,
    "tool_dispatch": _tool_dispatch,
    "tool_result": _tool_result,
    "notice": _notice,
    "approval_request": _approval,
    "ask_request": _ask,
    "compaction_started": _compaction_started,
    "compaction_progress": _compaction_progress,
    "compaction_done": _compaction_done,
    "turn_done": _turn_done,
    "stream_reset": _stream_reset,
    "todos": _todos,
}


def view_of(frame: Mapping[str, Any]) -> Item:
    """把一个 wire 帧投影成视图模型；任何异常形状都降级为 `UnsupportedItem`。"""

    kind = frame.get("kind")
    if not isinstance(kind, str) or not kind:
        return UnsupportedItem(kind="<unknown>", reason="帧缺少 kind 字段")
    project = _PROJECTIONS.get(kind)
    if project is None:
        return UnsupportedItem(kind=kind, reason=f"未登记的帧 kind：{kind}")
    try:
        return project(frame)
    except _Malformed as exc:
        return UnsupportedItem(kind=kind, reason=f"字段缺失或类型不符：{exc}")
