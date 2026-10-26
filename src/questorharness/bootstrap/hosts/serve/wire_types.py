"""AUTO-GENERATED from protocol/app-wire.schema.json. DO NOT EDIT."""

# ruff: noqa
# fmt: off

from __future__ import annotations

from typing import Final, Literal, NotRequired, TypedDict, Union


class ApprovalRequest(TypedDict):
    seq: int
    kind: Literal["approval_request"]
    id: str
    tool: str
    subject: str
    detail: NotRequired[str]
    patch: NotRequired[str]
    added: NotRequired[int]
    removed: NotRequired[int]


class ApproveRequest(TypedDict):
    id: str
    decision: Literal["approve", "deny"]


class AskAnswerRequest(TypedDict):
    id: str
    answer: str


class AskRequest(TypedDict):
    seq: int
    kind: Literal["ask_request"]
    id: str
    question: str


class CancelRequest(TypedDict):
    pass


class CatalogItem(TypedDict):
    """One row of a read-only catalog panel. Deliberately generic so every picker renders the same way (plan03 wave D)."""

    id: str
    label: str
    detail: NotRequired[str]
    current: NotRequired[bool]


class CatalogResponse(TypedDict):
    """HTTP response of GET /catalog/{kind}. Not a wire frame: it must stay out of ServerFrame or the web cardSlots equality guard would demand a card slot."""

    kind: Literal["sessions", "models", "skills", "mcp", "plugins", "jobs", "tasks", "git", "posture", "status"]
    items: list[CatalogItem]


class CompactionDone(TypedDict):
    seq: int
    kind: Literal["compaction_done"]
    trigger: Literal["auto", "manual", "reactive"]
    ok: bool


class CompactionProgress(TypedDict):
    seq: int
    kind: Literal["compaction_progress"]
    phase: Literal["hooks_start", "context_collapse_start", "context_collapse_end", "session_memory_start", "session_memory_end", "compact_start", "compact_retry", "compact_end", "compact_failed"]
    attempt: NotRequired[int]
    message: NotRequired[str]


class CompactionStarted(TypedDict):
    seq: int
    kind: Literal["compaction_started"]
    trigger: Literal["auto", "manual", "reactive"]


class ErrorBody(TypedDict):
    code: str
    message: str


class HistoryMessage(TypedDict):
    role: Literal["user", "assistant"]
    blocks: list[ContentBlock]


class HistoryResponse(TypedDict):
    sessionId: str
    messages: list[HistoryMessage]


class ImageBlock(TypedDict):
    type: Literal["image"]
    mediaType: str


class Message(TypedDict):
    seq: int
    kind: Literal["message"]
    blocks: list[ContentBlock]
    usage: NotRequired[Usage]


class Notice(TypedDict):
    seq: int
    kind: Literal["notice"]
    level: Literal["info", "warning", "error"]
    text: str


class ProfileResponse(TypedDict):
    id: str
    name: str
    description: str
    ui: ProfileUi


class ProfileUi(TypedDict):
    capabilities: CapabilityMap


class StreamReset(TypedDict):
    seq: int
    kind: Literal["stream_reset"]
    reason: Literal["replay_gap", "server_restart"]


class SubmitRequest(TypedDict):
    line: str
    clientRequestId: str


class SubmitResponse(TypedDict):
    """state=queued is reserved: the wire accepts it before the behaviour exists."""

    turnId: str
    state: Literal["started", "queued"]
    position: NotRequired[int]


class Text(TypedDict):
    seq: int
    kind: Literal["text"]
    text: str


class TextBlock(TypedDict):
    type: Literal["text"]
    text: str


class Todos(TypedDict):
    """Checklist snapshot after a todo_write tool call (plan03 W-D4). Derived by the host from the checklist file the tool just wrote; the engine events are unchanged."""

    seq: int
    kind: Literal["todos"]
    path: str
    items: list[dict[str, object]]


class ToolDispatch(TypedDict):
    seq: int
    kind: Literal["tool_dispatch"]
    toolCallId: str
    tool: str


class ToolResult(TypedDict):
    seq: int
    kind: Literal["tool_result"]
    toolCallId: str
    tool: str
    output: str
    isError: bool


class ToolResultBlock(TypedDict):
    type: Literal["tool_result"]
    toolUseId: str
    content: str
    isError: bool


class ToolUseBlock(TypedDict):
    type: Literal["tool_use"]
    id: str
    name: str


class TurnDone(TypedDict):
    seq: int
    kind: Literal["turn_done"]
    turnId: str
    cancelled: bool
    outcome: Literal["completed", "cancelled", "failed"]
    durationMs: int
    checkpointTurn: bool
    usage: NotRequired[Usage]


class TurnStarted(TypedDict):
    seq: int
    kind: Literal["turn_started"]
    turnId: str
    index: int
    via: Literal["cli", "studio", "api"]


class Usage(TypedDict):
    """Mirror of contracts/usage.py UsageSnapshot. The four extension fields are optional: the engine only produces input/output tokens today, the host fills what it can know (plan03 wave D)."""

    inputTokens: int
    outputTokens: int
    costUsd: NotRequired[float]
    contextWindow: NotRequired[int]
    contextUsed: NotRequired[int]
    cachedTokens: NotRequired[int]


CapabilityMap = dict[str, Literal["ready", "declared", "absent"]]


ContentBlock = Union[TextBlock, ImageBlock, ToolUseBlock, ToolResultBlock]


ServerFrame = Union[TurnStarted, Text, Message, ToolDispatch, ToolResult, ApprovalRequest, AskRequest, Notice, CompactionStarted, CompactionProgress, CompactionDone, TurnDone, StreamReset, Todos]


KIND_APPROVAL_REQUEST: Final[str] = "approval_request"
KIND_ASK_REQUEST: Final[str] = "ask_request"
KIND_COMPACTION_DONE: Final[str] = "compaction_done"
KIND_COMPACTION_PROGRESS: Final[str] = "compaction_progress"
KIND_COMPACTION_STARTED: Final[str] = "compaction_started"
KIND_MESSAGE: Final[str] = "message"
KIND_NOTICE: Final[str] = "notice"
KIND_STREAM_RESET: Final[str] = "stream_reset"
KIND_TEXT: Final[str] = "text"
KIND_TODOS: Final[str] = "todos"
KIND_TOOL_DISPATCH: Final[str] = "tool_dispatch"
KIND_TOOL_RESULT: Final[str] = "tool_result"
KIND_TURN_DONE: Final[str] = "turn_done"
KIND_TURN_STARTED: Final[str] = "turn_started"


SERVER_FRAME_KINDS: Final[frozenset[str]] = frozenset(
    {
        "approval_request",
        "ask_request",
        "compaction_done",
        "compaction_progress",
        "compaction_started",
        "message",
        "notice",
        "stream_reset",
        "text",
        "todos",
        "tool_dispatch",
        "tool_result",
        "turn_done",
        "turn_started",
    }
)


SERVER_FRAME_KIND_BY_DEF: Final[dict[str, str]] = {
    "ApprovalRequest": "approval_request",
    "AskRequest": "ask_request",
    "CompactionDone": "compaction_done",
    "CompactionProgress": "compaction_progress",
    "CompactionStarted": "compaction_started",
    "Message": "message",
    "Notice": "notice",
    "StreamReset": "stream_reset",
    "Text": "text",
    "Todos": "todos",
    "ToolDispatch": "tool_dispatch",
    "ToolResult": "tool_result",
    "TurnDone": "turn_done",
    "TurnStarted": "turn_started",
}
