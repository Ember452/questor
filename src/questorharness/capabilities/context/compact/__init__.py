"""Conversation compaction — microcompact and full LLM-based summarization.

Faithfully translated from Claude Code's compaction system:
- Microcompact: clear old tool result content to reduce token count cheaply
- Full compact: call the LLM to produce a structured summary of older messages
- Auto-compact: trigger compaction automatically when token count exceeds threshold
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal
from uuid import uuid4

from questorharness.capabilities.context.compact.attachments import (  # noqa: F401
    CompactAttachment,
    _build_compact_attachments,
    _extract_attachment_paths,
    _extract_discovered_tools,
    _replace_images_with_compaction_placeholders,
    _create_hook_attachments,
    _sanitize_metadata,
    create_async_agent_attachment_if_needed,
    create_invoked_skills_attachment_if_needed,
    create_plan_attachment_if_needed,
    create_recent_files_attachment_if_needed,
    create_recent_verified_work_attachment_if_needed,
    create_task_focus_attachment_if_needed,
    create_work_log_attachment_if_needed,
    render_compact_attachment,
)
from questorharness.capabilities.context.compact.collapse import (  # noqa: F401
    _split_preserving_tool_pairs,
    truncate_head_for_ptl_retry,
    try_context_collapse,
)
from questorharness.capabilities.context.compact.limits import *  # noqa: F403
from questorharness.capabilities.context.compact.limits import (  # noqa: F401
    _DEFAULT_CONTEXT_WINDOW,
    _DEFAULT_VISION_IMAGE_TOKEN_ESTIMATE,
)
from questorharness.capabilities.context.compact.prompts import (  # noqa: F401
    BASE_COMPACT_PROMPT,
    NO_TOOLS_PREAMBLE,
    NO_TOOLS_TRAILER,
    build_compact_summary_message,
    format_compact_summary,
    get_compact_prompt,
)
from questorharness.capabilities.context.compact.tokens import (  # noqa: F401
    estimate_conversation_tokens,
    estimate_message_tokens,
)
from questorharness.capabilities.ports import HookRuntime
from questorharness.contracts.domain.events import CompactProgressEvent
from questorharness.contracts.errors import is_prompt_too_long_error as _is_prompt_too_long_error
from questorharness.contracts.domain.message import (
    ContentBlock,
    ConversationMessage,
    ImageBlock,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    sanitize_conversation_messages,
)
from questorharness.contracts.hooks import HookEvent
from questorharness.contracts.tokens import estimate_tokens
from questorharness.contracts.tool_outputs import is_microcompactable_tool_result

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量（来自 Claude Code 的 microCompact.ts / autoCompact.ts）
# ---------------------------------------------------------------------------


# 自动压缩阈值

# 微压缩默认值

# Token 估算余量（保守值）

# 各模型家族的默认上下文窗口

CompactTrigger = Literal["auto", "manual", "reactive"]
CompactProgressCallback = Callable[[CompactProgressEvent], Awaitable[None]]
CompactionKind = Literal["full", "session_memory"]


@dataclass
class CompactionResult:
    """Structured compaction result, inspired by Claude Code's result shape."""

    trigger: CompactTrigger
    compact_kind: CompactionKind
    boundary_marker: ConversationMessage
    summary_messages: list[ConversationMessage]
    messages_to_keep: list[ConversationMessage]
    attachments: list[CompactAttachment]
    hook_results: list[CompactAttachment]
    compact_metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Token 估算
# ---------------------------------------------------------------------------


def _record_compact_checkpoint(
    carryover_metadata: dict[str, Any] | None,
    *,
    checkpoint: str,
    trigger: CompactTrigger,
    message_count: int,
    token_count: int,
    attempt: int | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "checkpoint": checkpoint,
        "trigger": trigger,
        "message_count": message_count,
        "token_count": token_count,
    }
    if attempt is not None:
        payload["attempt"] = attempt
    if details:
        payload.update(_sanitize_metadata(details))
    if carryover_metadata is not None:
        checkpoints = carryover_metadata.setdefault("compact_checkpoints", [])
        if isinstance(checkpoints, list):
            checkpoints.append(payload)
        carryover_metadata["compact_last"] = payload
    return payload


async def _emit_progress(
    callback: CompactProgressCallback | None,
    *,
    phase: Literal[
        "hooks_start",
        "context_collapse_start",
        "context_collapse_end",
        "session_memory_start",
        "session_memory_end",
        "compact_start",
        "compact_retry",
        "compact_end",
        "compact_failed",
    ],
    trigger: CompactTrigger,
    message: str | None = None,
    attempt: int | None = None,
    checkpoint: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    if callback is None:
        return
    await callback(
        CompactProgressEvent(
            phase=phase,
            trigger=trigger,
            message=message,
            attempt=attempt,
            checkpoint=checkpoint,
            metadata=_sanitize_metadata(metadata) if metadata else None,
        )
    )


def create_compact_boundary_message(metadata: dict[str, Any]) -> ConversationMessage:
    """Create a boundary marker message for post-compact conversation rebuild."""
    lines = [
        "[Compact boundary marker]",
        "Earlier conversation was compacted. Use the summary and preserved assets below as the continuity boundary.",
    ]
    trigger = str(metadata.get("trigger") or "").strip()
    compact_kind = str(metadata.get("compact_kind") or "").strip()
    pre_messages = metadata.get("pre_compact_message_count")
    pre_tokens = metadata.get("pre_compact_token_count")
    post_messages = metadata.get("post_compact_message_count")
    post_tokens = metadata.get("post_compact_token_count")
    if trigger:
        lines.append(f"Trigger: {trigger}")
    if compact_kind:
        lines.append(f"Compaction kind: {compact_kind}")
    if pre_messages is not None or pre_tokens is not None:
        lines.append(
            "Pre-compact footprint: "
            f"messages={pre_messages if pre_messages is not None else 'unknown'}, "
            f"tokens={pre_tokens if pre_tokens is not None else 'unknown'}"
        )
    if post_messages is not None or post_tokens is not None:
        lines.append(
            "Post-compact footprint: "
            f"messages={post_messages if post_messages is not None else 'unknown'}, "
            f"tokens={post_tokens if post_tokens is not None else 'unknown'}"
        )
    anchor = str(metadata.get("preserved_segment_anchor") or "").strip()
    if anchor:
        lines.append(f"Preserved segment anchor: {anchor}")
    return ConversationMessage.from_user_text("\n".join(lines))


def build_post_compact_messages(result: CompactionResult) -> list[ConversationMessage]:
    """Rebuild the post-compact message list in Claude Code's ordering."""
    attachment_messages = [render_compact_attachment(attachment) for attachment in result.attachments]
    hook_messages = [render_compact_attachment(attachment) for attachment in result.hook_results]
    return [
        result.boundary_marker,
        *result.summary_messages,
        *result.messages_to_keep,
        *attachment_messages,
        *hook_messages,
    ]


def _sanitize_compaction_segments(result: CompactionResult) -> None:
    """Normalize summary+preserved messages into a provider-safe sequence."""

    if not result.summary_messages and not result.messages_to_keep:
        return
    combined = [*result.summary_messages, *result.messages_to_keep]
    sanitized = sanitize_conversation_messages(combined)
    summary_count = len(result.summary_messages)
    result.summary_messages = sanitized[:summary_count]
    result.messages_to_keep = sanitized[summary_count:]


def _finalize_compaction_result(result: CompactionResult) -> CompactionResult:
    _sanitize_compaction_segments(result)
    messages = build_post_compact_messages(result)
    result.compact_metadata.setdefault("post_compact_message_count", len(messages))
    result.compact_metadata.setdefault("post_compact_token_count", estimate_message_tokens(messages))
    result.boundary_marker = create_compact_boundary_message(result.compact_metadata)
    return result


def _metadata_has_checkpoint(metadata: dict[str, Any] | None, checkpoint: str) -> bool:
    if metadata is None:
        return False
    checkpoints = metadata.get("compact_checkpoints")
    if not isinstance(checkpoints, list):
        return False
    return any(isinstance(entry, dict) and entry.get("checkpoint") == checkpoint for entry in checkpoints)


def _build_passthrough_compaction_result(
    messages: list[ConversationMessage],
    *,
    trigger: CompactTrigger,
    compact_kind: CompactionKind,
    metadata: dict[str, Any] | None = None,
) -> CompactionResult:
    compact_metadata = {
        "trigger": trigger,
        "compact_kind": compact_kind,
        "pre_compact_message_count": len(messages),
        "pre_compact_token_count": estimate_message_tokens(messages),
        **_sanitize_metadata(metadata or {}),
    }
    result = CompactionResult(
        trigger=trigger,
        compact_kind=compact_kind,
        boundary_marker=create_compact_boundary_message(compact_metadata),
        summary_messages=[],
        messages_to_keep=list(messages),
        attachments=[],
        hook_results=[],
        compact_metadata=compact_metadata,
    )
    return _finalize_compaction_result(result)


# ---------------------------------------------------------------------------
# 微压缩 — 清理旧工具结果，以低成本减少 token
# ---------------------------------------------------------------------------

def _collect_compactable_tool_ids(messages: list[ConversationMessage]) -> list[str]:
    """Walk messages and collect tool_use IDs whose results are compactable."""
    ordered_ids: list[str] = []
    tool_names: dict[str, str] = {}
    result_content: dict[str, str] = {}
    for msg in messages:
        for block in msg.content:
            if isinstance(block, ToolUseBlock):
                ordered_ids.append(block.id)
                tool_names[block.id] = block.name
            elif isinstance(block, ToolResultBlock):
                result_content[block.tool_use_id] = block.content
    return [
        tool_id
        for tool_id in ordered_ids
        if tool_names.get(tool_id, "") in compactable_tool_names()
        or is_microcompactable_tool_result(
            tool_names.get(tool_id, ""),
            result_content.get(tool_id, ""),
        )
    ]


def microcompact_messages(
    messages: list[ConversationMessage],
    *,
    keep_recent: int = DEFAULT_KEEP_RECENT,
) -> tuple[list[ConversationMessage], int]:
    """Clear old compactable tool results, keeping the most recent *keep_recent*.

    This is the cheap first pass — no LLM call required. Tool result content
    is replaced with :data:`TIME_BASED_MC_CLEARED_MESSAGE`.

    Returns:
        (messages, tokens_saved) — messages are mutated in place for efficiency.
    """
    keep_recent = max(1, keep_recent)  # 绝不清空所有结果
    all_ids = _collect_compactable_tool_ids(messages)

    if len(all_ids) <= keep_recent:
        return messages, 0

    keep_set = set(all_ids[-keep_recent:])
    clear_set = set(all_ids) - keep_set

    tokens_saved = 0
    for msg in messages:
        if msg.role != "user":
            continue
        new_content: list[ContentBlock] = []
        for block in msg.content:
            if (
                isinstance(block, ToolResultBlock)
                and block.tool_use_id in clear_set
                and block.content != TIME_BASED_MC_CLEARED_MESSAGE
            ):
                tokens_saved += estimate_tokens(block.content)
                new_content.append(
                    ToolResultBlock(
                        tool_use_id=block.tool_use_id,
                        content=TIME_BASED_MC_CLEARED_MESSAGE,
                        is_error=block.is_error,
                    )
                )
            else:
                new_content.append(block)
        msg.content = new_content

    if tokens_saved > 0:
        log.info("Microcompact cleared %d tool results, saved ~%d tokens", len(clear_set), tokens_saved)

    return messages, tokens_saved


def _summarize_message_for_memory(message: ConversationMessage) -> str:
    text = " ".join(message.text.split())
    if text:
        text = text[:160]
        return f"{message.role}: {text}"
    tool_uses = [block.name for block in message.tool_uses]
    if tool_uses:
        return f"{message.role}: tool calls -> {', '.join(tool_uses[:4])}"
    if any(isinstance(block, ToolResultBlock) for block in message.content):
        return f"{message.role}: tool results returned"
    return f"{message.role}: [non-text content]"


def _build_session_memory_message(messages: list[ConversationMessage]) -> ConversationMessage | None:
    lines: list[str] = []
    total_chars = 0
    for message in messages:
        line = _summarize_message_for_memory(message)
        if not line:
            continue
        projected = total_chars + len(line) + 1
        if lines and (len(lines) >= SESSION_MEMORY_MAX_LINES or projected >= SESSION_MEMORY_MAX_CHARS):
            lines.append("... earlier context condensed ...")
            break
        lines.append(line)
        total_chars = projected
    if not lines:
        return None
    body = "\n".join(lines)
    return ConversationMessage.from_user_text(
        "Session memory summary from earlier in this conversation:\n" + body
    )


def _build_file_session_memory_message(metadata: dict[str, Any] | None) -> ConversationMessage | None:
    """Build a compaction message from the persisted session-memory file."""

    if not metadata:
        return None
    path = metadata.get("session_memory_path")
    if not path:
        return None
    try:
        from questorharness.capabilities.memory.session import (
            get_session_memory_content,
            session_memory_to_compact_text,
        )

        text = session_memory_to_compact_text(get_session_memory_content(str(path)))
    except Exception:
        return None
    if not text.strip():
        return None
    return ConversationMessage.from_user_text(text)


def try_session_memory_compaction(
    messages: list[ConversationMessage],
    *,
    preserve_recent: int = SESSION_MEMORY_KEEP_RECENT,
    trigger: CompactTrigger = "auto",
    metadata: dict[str, Any] | None = None,
) -> CompactionResult | None:
    """Cheap deterministic compaction for long chats before full LLM compaction."""
    if len(messages) <= preserve_recent + 4:
        return None
    older, newer = _split_preserving_tool_pairs(messages, preserve_recent=preserve_recent)
    file_summary_message = _build_file_session_memory_message(metadata)
    summary_message = file_summary_message or _build_session_memory_message(older)
    if summary_message is None:
        return None
    provisional = [summary_message, *newer]
    if (
        estimate_message_tokens(provisional) >= estimate_message_tokens(messages)
        and len(provisional) >= len(messages)
    ):
        return None
    compact_metadata = {
        "trigger": trigger,
        "compact_kind": "session_memory",
        "pre_compact_message_count": len(messages),
        "pre_compact_token_count": estimate_message_tokens(messages),
        "preserve_recent": preserve_recent,
        "used_session_memory": True,
        "used_file_session_memory": file_summary_message is not None,
        "pre_compact_discovered_tools": _extract_discovered_tools(older),
        "attachments": _extract_attachment_paths(older),
    }
    result = CompactionResult(
        trigger=trigger,
        compact_kind="session_memory",
        boundary_marker=create_compact_boundary_message(compact_metadata),
        summary_messages=[summary_message],
        messages_to_keep=list(newer),
        attachments=_build_compact_attachments(older, metadata=metadata),
        hook_results=[],
        compact_metadata=compact_metadata,
    )
    return _finalize_compaction_result(result)


# ---------------------------------------------------------------------------
# 完整压缩 — 基于 LLM 的摘要
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 自动压缩跟踪
# ---------------------------------------------------------------------------

@dataclass
class AutoCompactState:
    """Mutable state that persists across query loop turns."""

    compacted: bool = False
    turn_counter: int = 0
    turn_id: str = ""
    consecutive_failures: int = 0


# ---------------------------------------------------------------------------
# 上下文窗口辅助函数
# ---------------------------------------------------------------------------

def get_context_window(model: str, *, context_window_tokens: int | None = None) -> int:
    """Return the context window size for a model (conservative defaults)."""
    if context_window_tokens is not None and context_window_tokens > 0:
        return int(context_window_tokens)
    m = model.lower()
    if "opus" in m:
        return 200_000
    if "sonnet" in m:
        return 200_000
    if "haiku" in m:
        return 200_000
    # Kimi / 其他提供商 — 采用保守值
    return _DEFAULT_CONTEXT_WINDOW


def get_autocompact_threshold(
    model: str,
    *,
    context_window_tokens: int | None = None,
    auto_compact_threshold_tokens: int | None = None,
) -> int:
    """Calculate the token count at which auto-compact fires."""
    if auto_compact_threshold_tokens is not None and auto_compact_threshold_tokens > 0:
        return int(auto_compact_threshold_tokens)
    context_window = get_context_window(model, context_window_tokens=context_window_tokens)
    reserved = min(MAX_OUTPUT_TOKENS_FOR_SUMMARY, 20_000)
    effective = context_window - reserved
    return effective - AUTOCOMPACT_BUFFER_TOKENS


def should_autocompact(
    messages: list[ConversationMessage],
    model: str,
    state: AutoCompactState,
    *,
    context_window_tokens: int | None = None,
    auto_compact_threshold_tokens: int | None = None,
) -> bool:
    """Return True when the conversation should be auto-compacted."""
    if state.consecutive_failures >= MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES:
        return False
    token_count = estimate_message_tokens(messages)
    threshold = get_autocompact_threshold(
        model,
        context_window_tokens=context_window_tokens,
        auto_compact_threshold_tokens=auto_compact_threshold_tokens,
    )
    return token_count >= threshold


# ---------------------------------------------------------------------------
# 完整压缩执行（调用 LLM）
# ---------------------------------------------------------------------------

async def compact_conversation(
    messages: list[ConversationMessage],
    *,
    api_client: Any,
    model: str,
    system_prompt: str = "",
    preserve_recent: int = 6,
    custom_instructions: str | None = None,
    suppress_follow_up: bool = True,
    trigger: CompactTrigger = "manual",
    progress_callback: CompactProgressCallback | None = None,
    emit_hooks_start: bool = True,
    hook_executor: HookRuntime | None = None,
    carryover_metadata: dict[str, Any] | None = None,
) -> CompactionResult:
    """Compact messages by calling the LLM to produce a summary.

    1. Microcompact first (cheap token reduction).
    2. Split into older (to summarize) and recent (to preserve).
    3. Call the LLM with the compact prompt to get a structured summary.
    4. Replace older messages with the summary + preserved recent messages.

    Args:
        messages: The full conversation history.
        api_client: An ``AnthropicApiClient`` or compatible for the summary call.
        model: Model ID to use for the summary.
        system_prompt: System prompt for the summary call.
        preserve_recent: Number of recent messages to keep verbatim.
        custom_instructions: Optional extra instructions for the summary prompt.
        suppress_follow_up: If True, instruct the model not to ask follow-ups.

    Returns:
        Structured compaction result that can be rebuilt into post-compact messages.
    """
    from questorharness.contracts.llm import ApiMessageCompleteEvent, ApiMessageRequest

    if len(messages) <= preserve_recent:
        return _build_passthrough_compaction_result(
            messages,
            trigger=trigger,
            compact_kind="full",
            metadata={"reason": "conversation already within preserve_recent window"},
        )

    # 步骤 1：先做微压缩，低成本减少 token
    messages, tokens_freed = microcompact_messages(messages, keep_recent=DEFAULT_KEEP_RECENT)

    pre_compact_tokens = estimate_message_tokens(messages)
    log.info("Compacting conversation: %d messages, ~%d tokens", len(messages), pre_compact_tokens)

    # 步骤 2：拆分为较旧（需摘要）和较新（需保留）两部分
    older, newer = _split_preserving_tool_pairs(messages, preserve_recent=preserve_recent)

    # 步骤 3：构建压缩请求 — 发送较旧消息 + 压缩提示词
    compact_prompt = get_compact_prompt(custom_instructions)
    compact_messages = list(older) + [ConversationMessage.from_user_text(compact_prompt)]
    attachment_paths = _extract_attachment_paths(older)
    discovered_tools = _extract_discovered_tools(older)
    hook_payload = {
        "event": HookEvent.PRE_COMPACT.value,
        "trigger": trigger,
        "model": model,
        "message_count": len(messages),
        "token_count": pre_compact_tokens,
        "preserve_recent": preserve_recent,
        "attachments": attachment_paths,
        "discovered_tools": discovered_tools,
        **(carryover_metadata or {}),
    }
    start_checkpoint = _record_compact_checkpoint(
        carryover_metadata,
        checkpoint="compact_prepare",
        trigger=trigger,
        message_count=len(messages),
        token_count=pre_compact_tokens,
        details={
            "preserve_recent": preserve_recent,
            "attachments": attachment_paths,
            "discovered_tools": discovered_tools,
        },
    )

    if emit_hooks_start:
        await _emit_progress(
            progress_callback,
            phase="hooks_start",
            trigger=trigger,
            message="Preparing conversation compaction.",
            checkpoint="compact_hooks_start",
            metadata=start_checkpoint,
        )
    if hook_executor is not None:
        hook_result = await hook_executor.execute(HookEvent.PRE_COMPACT, hook_payload)
        if hook_result.blocked:
            reason = hook_result.reason or "pre-compact hook blocked compaction"
            failed_checkpoint = _record_compact_checkpoint(
                carryover_metadata,
                checkpoint="compact_failed",
                trigger=trigger,
                message_count=len(messages),
                token_count=pre_compact_tokens,
                details={"reason": reason},
            )
            await _emit_progress(
                progress_callback,
                phase="compact_failed",
                trigger=trigger,
                message=reason,
                checkpoint="compact_failed",
                metadata=failed_checkpoint,
            )
            return _build_passthrough_compaction_result(
                messages,
                trigger=trigger,
                compact_kind="full",
                metadata={"reason": reason},
            )
    compact_start_checkpoint = _record_compact_checkpoint(
        carryover_metadata,
        checkpoint="compact_start",
        trigger=trigger,
        message_count=len(messages),
        token_count=pre_compact_tokens,
        details={"preserve_recent": preserve_recent},
    )
    await _emit_progress(
        progress_callback,
        phase="compact_start",
        trigger=trigger,
        message="Compacting conversation memory.",
        checkpoint="compact_start",
        metadata=compact_start_checkpoint,
    )

    summary_text = ""
    messages_to_summarize = compact_messages
    retry_messages = messages_to_summarize
    ptl_retries = 0

    async def _collect_summary(summary_request_messages: list[ConversationMessage]) -> str:
        collected = ""
        summary_request_messages = _replace_images_with_compaction_placeholders(
            summary_request_messages
        )
        stream = api_client.stream_message(
            ApiMessageRequest(
                model=model,
                messages=summary_request_messages,
                system_prompt=system_prompt or "You are a conversation summarizer.",
                max_tokens=MAX_OUTPUT_TOKENS_FOR_SUMMARY,
                tools=[],  # 压缩调用不携带工具
            )
        )
        if inspect.isawaitable(stream):
            stream = await stream
        if not hasattr(stream, "__aiter__"):
            raise RuntimeError("Compaction client did not provide a streaming response.")
        async for event in stream:
            if isinstance(event, ApiMessageCompleteEvent):
                collected = event.message.text
        if collected.strip():
            return collected
        raise RuntimeError(ERROR_MESSAGE_INCOMPLETE_RESPONSE)

    for attempt in range(1, MAX_COMPACT_STREAMING_RETRIES + 2):
        try:
            summary_text = await asyncio.wait_for(
                _collect_summary(retry_messages),
                timeout=COMPACT_TIMEOUT_SECONDS,
            )
            break
        except Exception as exc:
            if _is_prompt_too_long_error(exc) and ptl_retries < MAX_PTL_RETRIES:
                truncated = truncate_head_for_ptl_retry(retry_messages[:-1])
                if truncated:
                    ptl_retries += 1
                    retry_messages = [*truncated, retry_messages[-1]]
                    await _emit_progress(
                        progress_callback,
                        phase="compact_retry",
                        trigger=trigger,
                        message="Compaction prompt was too large; retrying with older context trimmed.",
                        attempt=ptl_retries,
                        checkpoint="compact_retry_prompt_too_long",
                        metadata=_record_compact_checkpoint(
                            carryover_metadata,
                            checkpoint="compact_retry_prompt_too_long",
                            trigger=trigger,
                            message_count=len(retry_messages),
                            token_count=estimate_message_tokens(retry_messages),
                            attempt=ptl_retries,
                            details={"ptl_retries": ptl_retries},
                        ),
                    )
                    continue
            if attempt > MAX_COMPACT_STREAMING_RETRIES:
                await _emit_progress(
                    progress_callback,
                    phase="compact_failed",
                    trigger=trigger,
                    message=str(exc),
                    attempt=attempt,
                    checkpoint="compact_failed",
                    metadata=_record_compact_checkpoint(
                        carryover_metadata,
                        checkpoint="compact_failed",
                        trigger=trigger,
                        message_count=len(retry_messages),
                        token_count=estimate_message_tokens(retry_messages),
                        attempt=attempt,
                        details={"reason": str(exc)},
                    ),
                )
                raise
            await _emit_progress(
                progress_callback,
                phase="compact_retry",
                trigger=trigger,
                message=str(exc),
                attempt=attempt,
                checkpoint="compact_retry",
                metadata=_record_compact_checkpoint(
                    carryover_metadata,
                    checkpoint="compact_retry",
                    trigger=trigger,
                    message_count=len(retry_messages),
                    token_count=estimate_message_tokens(retry_messages),
                    attempt=attempt,
                    details={"reason": str(exc)},
                ),
            )

    if not summary_text:
        await _emit_progress(
            progress_callback,
            phase="compact_failed",
            trigger=trigger,
            message=ERROR_MESSAGE_INCOMPLETE_RESPONSE,
            checkpoint="compact_failed",
            metadata=_record_compact_checkpoint(
                carryover_metadata,
                checkpoint="compact_failed",
                trigger=trigger,
                message_count=len(messages),
                token_count=pre_compact_tokens,
                details={"reason": ERROR_MESSAGE_INCOMPLETE_RESPONSE},
            ),
        )
        log.warning("Compact summary was empty — returning original messages")
        return _build_passthrough_compaction_result(
            messages,
            trigger=trigger,
            compact_kind="full",
            metadata={"reason": ERROR_MESSAGE_INCOMPLETE_RESPONSE},
        )

    # 步骤 4：构建新的消息列表
    summary_content = build_compact_summary_message(
        summary_text,
        suppress_follow_up=suppress_follow_up,
        recent_preserved=len(newer) > 0,
    )
    summary_msg = ConversationMessage.from_user_text(summary_content)
    initial_post_compact_tokens = estimate_message_tokens([summary_msg, *newer])
    if hook_executor is not None:
        post_hook_result = await hook_executor.execute(
            HookEvent.POST_COMPACT,
            {
                "event": HookEvent.POST_COMPACT.value,
                "trigger": trigger,
                "model": model,
                "pre_compact_message_count": len(messages),
                "post_compact_message_count": len(newer) + 1,
                "pre_compact_tokens": pre_compact_tokens,
                "post_compact_tokens": initial_post_compact_tokens,
                "attachments": attachment_paths,
                "discovered_tools": discovered_tools,
                **(carryover_metadata or {}),
            },
        )
        hook_note = post_hook_result.reason or "\n".join(
            result.output.strip()
            for result in post_hook_result.results
            if result.output.strip()
        )
        hook_attachments = _create_hook_attachments(hook_note)
    else:
        hook_attachments = []

    compact_metadata = {
        "trigger": trigger,
        "compact_kind": "full",
        "pre_compact_message_count": len(messages),
        "pre_compact_token_count": pre_compact_tokens,
        "preserve_recent": preserve_recent,
        "tokens_freed_by_microcompact": tokens_freed,
        "pre_compact_discovered_tools": discovered_tools,
        "used_head_truncation_retry": ptl_retries > 0,
        "used_context_collapse": _metadata_has_checkpoint(carryover_metadata, "query_context_collapse_end"),
        "used_session_memory": False,
        "retry_attempts": max(0, attempt - 1 if "attempt" in locals() else 0),
        "attachments": attachment_paths,
    }
    if carryover_metadata is not None:
        checkpoints = carryover_metadata.get("compact_checkpoints")
        if isinstance(checkpoints, list):
            compact_metadata["compact_checkpoints"] = checkpoints
        compact_last = carryover_metadata.get("compact_last")
        if isinstance(compact_last, dict):
            compact_metadata["compact_last"] = compact_last

    compaction_result = CompactionResult(
        trigger=trigger,
        compact_kind="full",
        boundary_marker=create_compact_boundary_message(compact_metadata),
        summary_messages=[summary_msg],
        messages_to_keep=list(newer),
        attachments=_build_compact_attachments(older, metadata=carryover_metadata),
        hook_results=hook_attachments,
        compact_metadata=compact_metadata,
    )
    compaction_result = _finalize_compaction_result(compaction_result)
    post_compact_messages = build_post_compact_messages(compaction_result)
    post_compact_tokens = estimate_message_tokens(post_compact_messages)
    compaction_result.compact_metadata["post_compact_message_count"] = len(post_compact_messages)
    compaction_result.compact_metadata["post_compact_token_count"] = post_compact_tokens
    compaction_result.boundary_marker = create_compact_boundary_message(compaction_result.compact_metadata)
    log.info(
        "Compaction done: %d -> %d messages, ~%d -> ~%d tokens (saved ~%d)",
        len(messages), len(post_compact_messages),
        pre_compact_tokens, post_compact_tokens,
        pre_compact_tokens - post_compact_tokens,
    )
    await _emit_progress(
        progress_callback,
        phase="compact_end",
        trigger=trigger,
        message="Conversation compaction complete.",
        checkpoint="compact_end",
        metadata=_record_compact_checkpoint(
            carryover_metadata,
            checkpoint="compact_end",
            trigger=trigger,
            message_count=len(post_compact_messages),
            token_count=post_compact_tokens,
            details={
                "pre_compact_message_count": len(messages),
                "post_compact_message_count": len(post_compact_messages),
                "pre_compact_tokens": pre_compact_tokens,
                "post_compact_tokens": post_compact_tokens,
                "tokens_saved": pre_compact_tokens - post_compact_tokens,
                "attachments": attachment_paths,
                "discovered_tools": discovered_tools,
            },
        ),
    )
    return compaction_result


# ---------------------------------------------------------------------------
# 自动压缩集成（由查询循环调用）
# ---------------------------------------------------------------------------

async def auto_compact_if_needed(
    messages: list[ConversationMessage],
    *,
    api_client: Any,
    model: str,
    system_prompt: str = "",
    state: AutoCompactState,
    preserve_recent: int = 6,
    progress_callback: CompactProgressCallback | None = None,
    force: bool = False,
    trigger: CompactTrigger = "auto",
    hook_executor: HookRuntime | None = None,
    carryover_metadata: dict[str, Any] | None = None,
    context_window_tokens: int | None = None,
    auto_compact_threshold_tokens: int | None = None,
) -> tuple[list[ConversationMessage], bool]:
    """Check if auto-compact should fire, and if so, compact.

    Call this at the start of each query loop turn.

    Returns:
        (messages, was_compacted) — if compacted, messages is the new list.
    """
    if not force and not should_autocompact(
        messages,
        model,
        state,
        context_window_tokens=context_window_tokens,
        auto_compact_threshold_tokens=auto_compact_threshold_tokens,
    ):
        return messages, False

    log.info("Auto-compact triggered (failures=%d)", state.consecutive_failures)
    _record_compact_checkpoint(
        carryover_metadata,
        checkpoint=f"query_{trigger}_triggered",
        trigger=trigger,
        message_count=len(messages),
        token_count=estimate_message_tokens(messages),
        details={"consecutive_failures": state.consecutive_failures},
    )

    # 先尝试微压缩 — 可能已足够
    messages, tokens_freed = microcompact_messages(messages)
    _record_compact_checkpoint(
        carryover_metadata,
        checkpoint="query_microcompact_end",
        trigger=trigger,
        message_count=len(messages),
        token_count=estimate_message_tokens(messages),
        details={"tokens_freed": tokens_freed},
    )
    if tokens_freed > 0 and not should_autocompact(
        messages,
        model,
        state,
        context_window_tokens=context_window_tokens,
        auto_compact_threshold_tokens=auto_compact_threshold_tokens,
    ):
        log.info("Microcompact freed ~%d tokens, auto-compact no longer needed", tokens_freed)
        return messages, True

    context_collapsed = try_context_collapse(messages, preserve_recent=preserve_recent)
    if context_collapsed is not None:
        await _emit_progress(
            progress_callback,
            phase="context_collapse_start",
            trigger=trigger,
            message="Collapsing oversized context before full compaction.",
            checkpoint="query_context_collapse_start",
            metadata=_record_compact_checkpoint(
                carryover_metadata,
                checkpoint="query_context_collapse_start",
                trigger=trigger,
                message_count=len(messages),
                token_count=estimate_message_tokens(messages),
            ),
        )
        messages = context_collapsed
        await _emit_progress(
            progress_callback,
            phase="context_collapse_end",
            trigger=trigger,
            message="Context collapse complete.",
            checkpoint="query_context_collapse_end",
            metadata=_record_compact_checkpoint(
                carryover_metadata,
                checkpoint="query_context_collapse_end",
                trigger=trigger,
                message_count=len(messages),
                token_count=estimate_message_tokens(messages),
            ),
        )
        if not force and not should_autocompact(
            messages,
            model,
            state,
            context_window_tokens=context_window_tokens,
            auto_compact_threshold_tokens=auto_compact_threshold_tokens,
        ):
            return messages, True

    session_memory = try_session_memory_compaction(
        messages,
        preserve_recent=max(preserve_recent, SESSION_MEMORY_KEEP_RECENT),
        trigger=trigger,
        metadata=carryover_metadata,
    )
    if session_memory is not None:
        await _emit_progress(
            progress_callback,
            phase="session_memory_start",
            trigger=trigger,
            message="Condensing earlier conversation into session memory.",
            checkpoint="query_session_memory_start",
            metadata=_record_compact_checkpoint(
                carryover_metadata,
                checkpoint="query_session_memory_start",
                trigger=trigger,
                message_count=len(messages),
                token_count=estimate_message_tokens(messages),
            ),
        )
        await _emit_progress(
            progress_callback,
            phase="session_memory_end",
            trigger=trigger,
            message="Session memory condensation complete.",
            checkpoint="query_session_memory_end",
            metadata=_record_compact_checkpoint(
                carryover_metadata,
                checkpoint="query_session_memory_end",
                trigger=trigger,
                message_count=len(build_post_compact_messages(session_memory)),
                token_count=estimate_message_tokens(build_post_compact_messages(session_memory)),
            ),
        )
        state.compacted = True
        state.turn_counter += 1
        state.turn_id = uuid4().hex
        state.consecutive_failures = 0
        return build_post_compact_messages(session_memory), True

    # 需要完整压缩
    try:
        result = await compact_conversation(
            messages,
            api_client=api_client,
            model=model,
            system_prompt=system_prompt,
            preserve_recent=preserve_recent,
            suppress_follow_up=True,
            trigger=trigger,
            progress_callback=progress_callback,
            hook_executor=hook_executor,
            carryover_metadata=carryover_metadata,
        )
        state.compacted = True
        state.turn_counter += 1
        state.turn_id = uuid4().hex
        state.consecutive_failures = 0
        return build_post_compact_messages(result), True
    except Exception as exc:
        state.consecutive_failures += 1
        _record_compact_checkpoint(
            carryover_metadata,
            checkpoint=f"query_{trigger}_failed",
            trigger=trigger,
            message_count=len(messages),
            token_count=estimate_message_tokens(messages),
            details={"reason": str(exc), "consecutive_failures": state.consecutive_failures},
        )
        log.error(
            "Auto-compact failed (attempt %d/%d): %s",
            state.consecutive_failures,
            MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES,
            exc,
        )
        return messages, False


# ---------------------------------------------------------------------------
# 旧版兼容
# ---------------------------------------------------------------------------

def summarize_messages(
    messages: list[ConversationMessage],
    *,
    max_messages: int = 8,
) -> str:
    """Produce a compact textual summary of recent messages (legacy)."""
    selected = messages[-max_messages:]
    lines: list[str] = []
    for message in selected:
        text = message.text.strip()
        if not text:
            continue
        lines.append(f"{message.role}: {text[:300]}")
    return "\n".join(lines)


def compact_messages(
    messages: list[ConversationMessage],
    *,
    preserve_recent: int = 6,
) -> list[ConversationMessage]:
    """Replace older conversation history with a synthetic summary (legacy)."""
    if len(messages) <= preserve_recent:
        return sanitize_conversation_messages(list(messages))
    older, newer = _split_preserving_tool_pairs(messages, preserve_recent=preserve_recent)
    summary = summarize_messages(older)
    if not summary:
        return list(newer)
    return sanitize_conversation_messages([
        ConversationMessage(
            role="user",
            content=[TextBlock(text=f"[conversation summary]\n{summary}")],
        ),
        *newer,
    ])


__all__ = [
    "AUTO_COMPACT_BUFFER_TOKENS",
    "AutoCompactState",
    "CompactAttachment",
    "CompactionResult",
    "compactable_tool_names",
    "TIME_BASED_MC_CLEARED_MESSAGE",
    "auto_compact_if_needed",
    "build_post_compact_messages",
    "build_compact_summary_message",
    "compact_conversation",
    "compact_messages",
    "create_compact_boundary_message",
    "estimate_conversation_tokens",
    "estimate_message_tokens",
    "format_compact_summary",
    "get_autocompact_threshold",
    "get_compact_prompt",
    "microcompact_messages",
    "should_autocompact",
    "summarize_messages",
]

# questor: allow R2 -- 1171 lines until W8 splits this file (ledger row 86)
# questor: allow R4 -- split when a test proves patching should_autocompact still bites
# questor: allow R5 -- 20 exports until the R4 split above lands
# questor: allow R8 -- refactor compact_conversation (CC 42) in W8, after the split
