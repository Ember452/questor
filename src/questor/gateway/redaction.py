"""Redaction and shaping of gateway messages before they leave the process.

Everything here is pure: it takes engine/channel objects and returns new ones. No
filesystem, no network, no runtime pool -- which is why it can be reviewed as the privacy
layer on its own. ``runtime.py`` (the session pool and the lifecycle the tests patch)
imports these helpers; nothing imports back.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from questor.gateway.media import _build_attachment_notes, _is_image_attachment
from questorharness.api import ConversationMessage, ImageBlock, InboundMessage, TextBlock

logger = logging.getLogger(__name__)

_CHANNEL_THINKING_PHRASES = (
    "🤔 想一想…",
    "🧠 琢磨中…",
    "✨ 整理一下思路…",
    "🔎 看看这个…",
    "🪄 捋一捋线索…",
)
_CHANNEL_THINKING_PHRASES_EN = (
    "🤔 Thinking…",
    "🧠 Working through it…",
    "✨ Pulling the pieces together…",
    "🔎 Looking into it…",
    "🪄 Following the thread…",
)
_IMAGE_FALLBACK_NOTE = (
    "[Image attachment omitted because the active model does not support image input. "
    "Use the attachment paths and summaries above if needed.]"
)
_GROUP_AGENT_PROMPT_PREFIX = "The user invoked `/group` from a Feishu private chat."
_GROUP_AGENT_PROMPT_REQUEST_MARKER = "User /group request:"
_GROUP_METADATA_KEYS = (
    "task_focus_state",
    "recent_work_log",
    "recent_verified_work",
    "compact_checkpoints",
    "compact_last",
)


def _content_snippet(text: str, *, limit: int = 160) -> str:
    """Return a compact single-line preview for logs."""
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def _sanitize_snapshot_messages(raw_messages: object) -> list[dict[str, object]] | None:
    """Validate and sanitize restored messages from persisted questor snapshots."""
    if not raw_messages or not isinstance(raw_messages, list):
        return None
    messages: list[ConversationMessage] = []
    for raw in raw_messages:
        try:
            messages.append(ConversationMessage.model_validate(raw))
        except Exception:
            logger.warning("questor runtime skipped invalid restored message while sanitizing snapshot")
    return [message.model_dump(mode="json") for message in _sanitize_group_command_prompts(messages)]


def _sanitize_group_command_prompts(messages: list[ConversationMessage]) -> list[ConversationMessage]:
    """Replace internal /group tool-driving prompts with durable user-facing history."""
    return [_sanitize_group_command_prompt(message) for message in messages]


def _sanitize_group_command_prompt(message: ConversationMessage) -> ConversationMessage:
    changed = False
    # ``list[Any]`` on purpose: the block union is ``ContentBlock``, which the public
    # ``questorharness.api`` face does not re-export, and importing it from
    # ``questorharness.contracts`` would break the product-uses-public-face contract.
    content: list[Any] = []
    for block in message.content:
        if isinstance(block, TextBlock) and _GROUP_AGENT_PROMPT_PREFIX in block.text:
            content.append(TextBlock(text=_format_group_command_history_note(block.text)))
            changed = True
        else:
            content.append(block)
    if not changed:
        return message
    return message.model_copy(update={"content": content})


def _format_group_command_history_note(prompt: str) -> str:
    raw_request = prompt
    if _GROUP_AGENT_PROMPT_REQUEST_MARKER in prompt:
        raw_request = prompt.split(_GROUP_AGENT_PROMPT_REQUEST_MARKER, 1)[1].strip()
    raw_request = raw_request.strip() or "(empty request)"
    return f"[Handled /group request]\nThe user asked questor to create a Feishu group:\n{raw_request}"


def _sanitize_group_command_metadata(raw_metadata: object) -> object:
    """Remove internal /group tool-driving text from compact carry-over metadata."""
    if not isinstance(raw_metadata, dict):
        return raw_metadata
    sanitized = dict(raw_metadata)
    for key in _GROUP_METADATA_KEYS:
        if key in sanitized:
            sanitized[key] = _sanitize_group_command_metadata_value(sanitized[key])
    return sanitized


def _sanitize_group_command_metadata_value(value: object) -> object:
    if isinstance(value, str):
        if _GROUP_AGENT_PROMPT_PREFIX in value:
            return _format_group_command_history_note(value)
        return value
    if isinstance(value, dict):
        return {key: _sanitize_group_command_metadata_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_group_command_metadata_value(item) for item in value]
    return value


def _summarize_tool_input(tool_name: str, tool_input: dict[str, object]) -> str:
    if not tool_input:
        return ""
    for key in ("url", "query", "pattern", "path", "file_path", "command"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip()
            return text if len(text) <= 120 else text[:120] + "..."
    try:
        raw = json.dumps(tool_input, ensure_ascii=False, sort_keys=True)
    except TypeError:
        raw = str(tool_input)
    return raw if len(raw) <= 120 else raw[:120] + "..."


def _format_channel_progress(
    *,
    channel: str,
    kind: str,
    text: str,
    session_key: str,
    content: str,
    compact_phase: str | None = None,
    compact_trigger: str | None = None,
    attempt: int | None = None,
) -> str:
    if channel not in {"feishu", "qq"}:
        return text
    prefers_chinese = _prefers_chinese_progress(content)
    if kind == "thinking":
        seed = f"{session_key}|{content}".encode()
        phrases = _CHANNEL_THINKING_PHRASES if prefers_chinese else _CHANNEL_THINKING_PHRASES_EN
        idx = int(hashlib.sha256(seed).hexdigest(), 16) % len(phrases)
        return phrases[idx]
    if kind == "tool_hint":
        if prefers_chinese:
            if text.startswith("Using "):
                return "🛠️ " + text.replace("Using ", "正在使用 ", 1)
            return f"🛠️ {text}"
        return text if text.startswith("🛠️ ") else f"🛠️ {text}"
    if kind == "image_fallback":
        if prefers_chinese:
            return "🖼️ 当前模型不支持图片输入，我先改用附件路径和摘要继续。"
        return "🖼️ The active model does not support image input. I’ll retry with attachment paths and summaries."
    if kind == "status":
        normalized = text.strip()
        if normalized == "Auto-compacting conversation memory to keep things fast and focused.":
            if prefers_chinese:
                return "🧠 聊天有点长啦，我先帮你蹦蹦跳跳压缩一下记忆，马上带着重点回来～"
            return "🧠 This chat is getting long — I’m doing a quick memory squeeze and hopping right back with the good bits."
        if text.startswith(("🤔", "🧠", "✨", "🔎", "🪄", "🛠️", "🫧")):
            return text
        return f"🫧 {text}"
    if kind == "compact_progress":
        if compact_phase == "hooks_start":
            if prefers_chinese:
                if compact_trigger == "reactive":
                    return "🫧 上下文有点超长，我先准备压缩一下记忆，然后立刻继续重试～"
                return "🫧 我先把上下文和记忆准备一下，马上开始压缩重点～"
            if compact_trigger == "reactive":
                return "🫧 The context got too large. I’m preparing a quick memory compaction before retrying."
            return "🫧 Let me get the context ready before I compact the conversation."
        if compact_phase == "context_collapse_start":
            if prefers_chinese:
                return "🫧 我先把太长的上下文折叠一下，让后面的压缩更快一点～"
            return "🫧 I’m collapsing the oversized context first so compaction can move faster."
        if compact_phase == "context_collapse_end":
            if prefers_chinese:
                return "🫧 上下文已经先收紧了一层，继续压缩重点～"
            return "🫧 The context is trimmed down now. Continuing with the main compaction."
        if compact_phase in {"session_memory_start", "compact_start"}:
            if prefers_chinese:
                if compact_phase == "session_memory_start":
                    return "🧠 我先把前面的聊天重点悄悄捋顺一下，马上继续～"
                if compact_trigger == "reactive":
                    return "🧠 这轮上下文太长了，我先压缩一下记忆，然后马上继续重试～"
                return "🧠 聊天有点长啦，我先帮你悄悄压缩一下记忆，马上继续～"
            if compact_phase == "session_memory_start":
                return "🧠 Let me quickly condense the earlier parts of this chat, then I’ll keep going."
            if compact_trigger == "reactive":
                return "🧠 The context is too large for this turn. I’ll compact the memory and retry."
            return "🧠 This chat is getting long. I’ll compact the memory and keep going."
        if compact_phase == "compact_retry":
            suffix = f" (attempt {attempt})" if attempt is not None else ""
            if prefers_chinese:
                return f"🔁 压缩记忆这一步有点卡，我换个方式再试一次{suffix}。"
            return f"🔁 Compaction got stuck, trying a lighter retry{suffix}."
        if compact_phase == "compact_failed":
            if prefers_chinese:
                return "⚠️ 这次记忆压缩没成功，我先跳过它继续处理你的消息。"
            return "⚠️ Memory compaction did not complete. I’m skipping it and continuing."
        return ""
    return text


def _build_inbound_user_message(message: InboundMessage) -> ConversationMessage:
    """Convert an inbound channel message into user content blocks."""
    content: list[Any] = []
    speaker_context = _build_speaker_context(message)
    base = (message.content or "").strip()
    if speaker_context:
        content.append(TextBlock(text=speaker_context))
    if base:
        content.append(TextBlock(text=base))

    attachment_notes = _build_attachment_notes(message.media)
    if attachment_notes:
        prefix = "\n\n" if base else ""
        content.append(TextBlock(text=prefix + attachment_notes))

    for media_path in message.media:
        if not _is_image_attachment(media_path):
            continue
        try:
            content.append(ImageBlock.from_path(media_path))
        except Exception:
            logger.exception("questor runtime failed to encode image attachment path=%s", media_path)

    return ConversationMessage.from_user_content(content)


def _should_retry_without_image_input(error_message: str, messages: list[ConversationMessage]) -> bool:
    """Return True when a provider rejects image input and history contains images."""
    if not _history_has_image_blocks(messages):
        return False
    normalized = error_message.lower()
    image_signal = any(
        phrase in normalized
        for phrase in (
            "image input",
            "image_url",
            "multimodal",
            "vision",
            "image content",
        )
    )
    rejection_signal = any(
        phrase in normalized
        for phrase in (
            "no endpoints found",
            "not support",
            "does not support",
            "unsupported",
            "cannot support",
            "can't support",
        )
    )
    return image_signal and rejection_signal


def _history_has_image_blocks(messages: list[ConversationMessage]) -> bool:
    return any(any(isinstance(block, ImageBlock) for block in message.content) for message in messages)


def _strip_image_blocks_from_engine_history(engine: Any) -> None:
    """Replace image blocks in a live engine, through whichever API it exposes."""
    messages = _strip_image_blocks_from_messages(list(engine.messages))
    if hasattr(engine, "load_messages"):
        engine.load_messages(messages)
    else:
        engine.messages = messages


def _strip_image_blocks_from_messages(messages: list[ConversationMessage]) -> list[ConversationMessage]:
    return [_strip_image_blocks_from_message(message) for message in messages]


def _strip_image_blocks_from_message(message: ConversationMessage) -> ConversationMessage:
    if not any(isinstance(block, ImageBlock) for block in message.content):
        return message
    content = [block for block in message.content if not isinstance(block, ImageBlock)]
    if not any(isinstance(block, TextBlock) for block in content):
        content.append(TextBlock(text=_IMAGE_FALLBACK_NOTE))
    return message.model_copy(update={"content": content})


def _build_speaker_context(message: InboundMessage) -> str:
    """Return a lightweight speaker header for group-chat messages."""
    metadata = message.metadata or {}
    chat_type = str(metadata.get("chat_type") or "").strip().lower()
    sender_label = (
        str(metadata.get("sender_display_name") or "").strip()
        or str(metadata.get("sender_label") or "").strip()
        or str(message.sender_id).strip()
    )
    if chat_type != "group":
        return ""
    if not sender_label:
        sender_label = "unknown"
    return (
        "[Channel speaker]\n"
        f"This message was sent in a group chat by: {sender_label}\n"
        f"Sender id: {message.sender_id}"
    )


def _prefers_chinese_progress(content: str) -> bool:
    cjk_count = 0
    latin_count = 0
    for char in content:
        codepoint = ord(char)
        if (
            0x4E00 <= codepoint <= 0x9FFF
            or 0x3400 <= codepoint <= 0x4DBF
            or 0x20000 <= codepoint <= 0x2A6DF
            or 0x2A700 <= codepoint <= 0x2B73F
            or 0x2B740 <= codepoint <= 0x2B81F
            or 0x2B820 <= codepoint <= 0x2CEAF
            or 0xF900 <= codepoint <= 0xFAFF
        ):
            cjk_count += 1
        elif ("A" <= char <= "Z") or ("a" <= char <= "z"):
            latin_count += 1
    if cjk_count == 0:
        return False
    if latin_count == 0:
        return True
    return cjk_count >= latin_count

# questor: allow R8 -- _format_channel_progress cyclomatic 34, until a gateway progress-text knife (ledger #117)
