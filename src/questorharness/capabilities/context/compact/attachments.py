"""Compaction attachments."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from questorharness.capabilities.context.compact.limits import *  # noqa: F403
from questorharness.capabilities.context.compact.limits import (  # noqa: F401
    COMPACT_TIMEOUT_SECONDS,
    CONTEXT_COLLAPSE_HEAD_CHARS,
    CONTEXT_COLLAPSE_TAIL_CHARS,
    CONTEXT_COLLAPSE_TEXT_CHAR_LIMIT,
    MAX_COMPACT_ATTACHMENTS,
    MAX_DISCOVERED_TOOLS,
    TIME_BASED_MC_CLEARED_MESSAGE,
)
from questorharness.contracts.domain.message import (
    ContentBlock,
    ConversationMessage,
    ImageBlock,
    TextBlock,
)


@dataclass
class CompactAttachment:
    """Structured compact asset carried across a compaction boundary."""

    kind: str
    title: str
    body: str
    metadata: dict[str, Any] = field(default_factory=dict)

def _replace_images_with_compaction_placeholders(
    messages: list[ConversationMessage],
) -> list[ConversationMessage]:
    """Strip image payloads from summarizer-only compact requests."""
    replaced: list[ConversationMessage] = []
    for message in messages:
        next_content: list[ContentBlock] = []
        changed = False
        for block in message.content:
            if isinstance(block, ImageBlock):
                changed = True
                label = block.source_path.strip() or "inline"
                next_content.append(
                    TextBlock(
                        text=f"[Image omitted from compaction summarization; source: {label}.]\n"
                    )
                )
            else:
                next_content.append(block)
        if changed:
            replaced.append(message.model_copy(update={"content": next_content}))
        else:
            replaced.append(message)
    return replaced

def _sanitize_metadata(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _sanitize_metadata(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_metadata(item) for item in value]
    return str(value)

def _extract_attachment_paths(messages: list[ConversationMessage]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    path_pattern = re.compile(r"path:\s*([^)\\n]+)")
    attachment_pattern = re.compile(r"\[attachment:\s*([^\]]+)\]")
    for message in messages:
        for block in message.content:
            if isinstance(block, ImageBlock) and block.source_path:
                path = str(Path(block.source_path).expanduser())
                if path not in seen:
                    seen.add(path)
                    found.append(path)
            elif isinstance(block, TextBlock):
                for match in path_pattern.findall(block.text):
                    path = match.strip()
                    if path and path not in seen:
                        seen.add(path)
                        found.append(path)
                for match in attachment_pattern.findall(block.text):
                    path = match.strip()
                    if path and "download failed" not in path and path not in seen:
                        seen.add(path)
                        found.append(path)
            if len(found) >= MAX_COMPACT_ATTACHMENTS:
                return found
    return found

def _extract_discovered_tools(messages: list[ConversationMessage]) -> list[str]:
    discovered: list[str] = []
    seen: set[str] = set()
    for message in messages:
        for tool_use in message.tool_uses:
            if tool_use.name and tool_use.name not in seen:
                seen.add(tool_use.name)
                discovered.append(tool_use.name)
            if len(discovered) >= MAX_DISCOVERED_TOOLS:
                return discovered
    return discovered

def _create_attachment(kind: str, title: str, lines: list[str], *, metadata: dict[str, Any] | None = None) -> CompactAttachment | None:
    filtered = [line.rstrip() for line in lines if line and line.strip()]
    if not filtered:
        return None
    return CompactAttachment(
        kind=kind,
        title=title,
        body="\n".join(filtered),
        metadata=_sanitize_metadata(metadata or {}),
    )

def render_compact_attachment(attachment: CompactAttachment) -> ConversationMessage:
    """Serialize a structured compact attachment into a conversation message."""
    header = f"[Compact attachment: {attachment.kind}] {attachment.title}".strip()
    text = f"{header}\n{attachment.body}".strip()
    return ConversationMessage.from_user_text(text)

def _create_recent_attachments_attachment_if_needed(
    attachment_paths: list[str],
) -> CompactAttachment | None:
    if not attachment_paths:
        return None
    return _create_attachment(
        "recent_attachments",
        "Recent local attachments",
        ["Keep these local attachment paths in working memory:"] + [f"- {path}" for path in attachment_paths],
        metadata={"paths": attachment_paths},
    )

def create_recent_files_attachment_if_needed(
    read_file_state: Any,
) -> CompactAttachment | None:
    if not isinstance(read_file_state, list) or not read_file_state:
        return None
    lines = ["Recently read files that may still matter:"]
    entries: list[dict[str, Any]] = []
    normalized_entries = [
        entry
        for entry in read_file_state
        if isinstance(entry, dict) and str(entry.get("path") or "").strip()
    ]
    normalized_entries.sort(
        key=lambda entry: float(entry.get("timestamp") or 0.0),
        reverse=True,
    )
    for entry in normalized_entries[:4]:
        if not isinstance(entry, dict):
            continue
        path = str(entry.get("path") or "").strip()
        span = str(entry.get("span") or "").strip()
        preview = str(entry.get("preview") or "").strip()
        timestamp = entry.get("timestamp")
        if not path:
            continue
        bullet = f"- {path}"
        if span:
            bullet += f" ({span})"
        lines.append(bullet)
        if preview:
            lines.append(f"  Preview: {preview}")
        entries.append({"path": path, "span": span, "preview": preview, "timestamp": timestamp})
    return _create_attachment("recent_files", "Recently read files", lines, metadata={"entries": entries})

def create_task_focus_attachment_if_needed(
    metadata: dict[str, Any],
) -> CompactAttachment | None:
    state = metadata.get("task_focus_state")
    if not isinstance(state, dict):
        return None
    goal = str(state.get("goal") or "").strip()
    recent_goals = [
        str(item).strip()
        for item in state.get("recent_goals", [])
        if str(item).strip()
    ]
    active_artifacts = [
        str(item).strip()
        for item in state.get("active_artifacts", [])
        if str(item).strip()
    ]
    verified_state = [
        str(item).strip()
        for item in state.get("verified_state", [])
        if str(item).strip()
    ]
    next_step = str(state.get("next_step") or "").strip()
    if not any((goal, recent_goals, active_artifacts, verified_state, next_step)):
        return None
    lines = ["Current working focus to preserve across compaction:"]
    if goal:
        lines.append(f"- Goal: {goal}")
    if recent_goals:
        lines.append("- Recent user goals that still matter:")
        lines.extend(f"  - {item}" for item in recent_goals[-3:])
    if active_artifacts:
        lines.append("- Active artifacts in play:")
        lines.extend(f"  - {item}" for item in active_artifacts[-5:])
    if verified_state:
        lines.append("- Verified state already established:")
        lines.extend(f"  - {item}" for item in verified_state[-4:])
    if next_step:
        lines.append(f"- Suggested next step: {next_step}")
    return _create_attachment(
        "task_focus",
        "Current working focus",
        lines,
        metadata={
            "goal": goal,
            "recent_goals": recent_goals[-3:],
            "active_artifacts": active_artifacts[-5:],
            "verified_state": verified_state[-4:],
            "next_step": next_step,
        },
    )

def create_recent_verified_work_attachment_if_needed(
    verified_work: Any,
) -> CompactAttachment | None:
    if not isinstance(verified_work, list) or not verified_work:
        return None
    entries = [str(entry).strip() for entry in verified_work[-8:] if str(entry).strip()]
    if not entries:
        return None
    return _create_attachment(
        "recent_verified_work",
        "Recently verified work",
        ["These steps or conclusions were explicitly verified before compaction:"] + [f"- {entry}" for entry in entries],
        metadata={"entries": entries},
    )

def create_plan_attachment_if_needed(metadata: dict[str, Any]) -> CompactAttachment | None:
    permission_mode = str(metadata.get("permission_mode") or "").strip().lower()
    if permission_mode != "plan":
        return None
    lines = [
        "Plan mode is still active for this session.",
        "Do not execute mutating tools until the user explicitly exits plan mode.",
    ]
    plan_summary = str(metadata.get("plan_summary") or "").strip()
    if plan_summary:
        lines.append(f"Current plan summary: {plan_summary}")
    return _create_attachment(
        "plan",
        "Plan mode context",
        lines,
        metadata={"permission_mode": permission_mode, "plan_summary": plan_summary},
    )

def create_invoked_skills_attachment_if_needed(
    invoked_skills: Any,
) -> CompactAttachment | None:
    if not isinstance(invoked_skills, list) or not invoked_skills:
        return None
    normalized = [str(skill).strip() for skill in invoked_skills[-8:] if str(skill).strip()]
    if not normalized:
        return None
    return _create_attachment(
        "invoked_skills",
        "Skills used earlier in the session",
        ["The following skills were invoked and may still shape the next step:", "- " + ", ".join(normalized)],
        metadata={"skills": normalized},
    )

def create_async_agent_attachment_if_needed(
    async_agent_state: Any,
) -> CompactAttachment | None:
    if not isinstance(async_agent_state, list) or not async_agent_state:
        return None
    entries = [str(entry).strip() for entry in async_agent_state[-6:] if str(entry).strip()]
    if not entries:
        return None
    return _create_attachment(
        "async_agents",
        "Async agent and background task state",
        ["Recent async-agent/background-task activity:"] + [f"- {entry}" for entry in entries],
        metadata={"entries": entries},
    )

def create_work_log_attachment_if_needed(
    recent_work_log: Any,
) -> CompactAttachment | None:
    if not isinstance(recent_work_log, list) or not recent_work_log:
        return None
    entries = [str(entry).strip() for entry in recent_work_log[-8:] if str(entry).strip()]
    if not entries:
        return None
    return _create_attachment(
        "recent_work_log",
        "Recent execution checkpoints",
        ["Recent work and verification steps taken in this session:"] + [f"- {entry}" for entry in entries],
        metadata={"entries": entries},
    )

def _create_hook_attachments(hook_note: str | None) -> list[CompactAttachment]:
    if not hook_note or not hook_note.strip():
        return []
    attachment = _create_attachment(
        "hook_results",
        "Compact hook notes",
        [hook_note.strip()],
        metadata={"note": hook_note.strip()},
    )
    return [attachment] if attachment is not None else []

def _build_compact_attachments(
    messages: list[ConversationMessage],
    *,
    metadata: dict[str, Any] | None,
) -> list[CompactAttachment]:
    metadata = metadata or {}
    attachments: list[CompactAttachment] = []
    attachment_paths = _extract_attachment_paths(messages)
    builders = [
        create_task_focus_attachment_if_needed(metadata),
        create_recent_verified_work_attachment_if_needed(metadata.get("recent_verified_work")),
        _create_recent_attachments_attachment_if_needed(attachment_paths),
        create_recent_files_attachment_if_needed(metadata.get("read_file_state")),
        create_plan_attachment_if_needed(metadata),
        create_invoked_skills_attachment_if_needed(metadata.get("invoked_skills")),
        create_async_agent_attachment_if_needed(metadata.get("async_agent_state")),
        create_work_log_attachment_if_needed(metadata.get("recent_work_log")),
    ]
    attachments.extend(attachment for attachment in builders if attachment is not None)
    return attachments

# questor: allow R7 -- until W8 adds the mirror test
