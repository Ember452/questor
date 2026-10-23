"""Run a durable memory extraction pass.

Moved out of ``memory/extract/__init__.py`` by plan 01 W8. Parsing lives in
:mod:`records`; what the agent may touch lives in :mod:`guard`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast

from questorharness.capabilities.memory.extract.guard import has_memory_writes_since
from questorharness.capabilities.memory.extract.records import (
    ExtractionRecord,
    ExtractionResult,
    parse_extraction_records,
)
from questorharness.capabilities.memory.manager import add_memory_entry
from questorharness.capabilities.memory.paths import get_project_memory_dir
from questorharness.capabilities.memory.relevance import build_memory_manifest
from questorharness.capabilities.memory.scan import scan_memory_files
from questorharness.capabilities.memory.team import check_team_memory_secrets, validate_team_memory_write_path
from questorharness.contracts.domain.message import ConversationMessage
from questorharness.contracts.llm import (
    ApiMessageCompleteEvent,
    ApiMessageRequest,
    ApiStreamEvent,
    SupportsStreamingMessages,
)

log = logging.getLogger(__name__)

EXTRACTION_SYSTEM_PROMPT = """You maintain QuestorHarness durable memory.
Save only stable, future-useful facts that are not derivable from current files,
git history, or documentation. Prefer updating existing memories conceptually
over duplicating them. Do not save secrets. If nothing is worth saving, return
{"memories": []}.
"""


async def extract_memories_from_turn(
    *,
    cwd: str | Path,
    api_client: SupportsStreamingMessages,
    model: str,
    messages: list[ConversationMessage],
    max_records: int = 3,
) -> ExtractionResult:
    """Ask the model for durable memory candidates and apply them."""

    memory_dir = get_project_memory_dir(cwd)
    if len(messages) < 2:
        return ExtractionResult(skipped=True, reason="not enough messages")
    if has_memory_writes_since(messages, memory_dir, cwd=cwd):
        return ExtractionResult(skipped=True, reason="main conversation already wrote memory")

    prompt = build_extraction_prompt(cwd, messages, max_records=max_records)
    final_text = ""
    # SupportsStreamingMessages.stream_message is declared ``async def ... ->
    # AsyncIterator[...]`` while every implementation is an async generator, so the
    # call already returns the iterator; the declaration is wrong repo-wide and is
    # fixed where contracts are owned (plan 01 ledger row 82), not here.
    stream = cast("AsyncIterator[ApiStreamEvent]", api_client.stream_message(
        ApiMessageRequest(
            model=model,
            messages=[ConversationMessage.from_user_text(prompt)],
            system_prompt=EXTRACTION_SYSTEM_PROMPT,
            max_tokens=2048,
            tools=[],
        )
    ))
    async for event in stream:
        if isinstance(event, ApiMessageCompleteEvent):
            final_text = event.message.text
            break
    records = parse_extraction_records(final_text, max_records=max_records)
    if not records:
        return ExtractionResult(skipped=True, reason="no durable memories proposed")
    return apply_extraction_records(cwd, records)


def build_extraction_prompt(cwd: str | Path, messages: list[ConversationMessage], *, max_records: int) -> str:
    """Build the extraction request from recent messages and manifest."""

    manifest = build_memory_manifest(scan_memory_files(cwd, max_files=80))
    transcript = "\n".join(_summarize_message(message) for message in messages[-12:])
    return (
        "Extract only durable memories from the recent conversation.\n"
        f"Return JSON with at most {max_records} records. Existing memory manifest:\n"
        f"{manifest or '(empty)'}\n\n"
        "Recent conversation:\n"
        f"{transcript}\n\n"
        "JSON schema: {\"memories\":[{\"title\":\"...\",\"type\":\"user|feedback|project|reference\","
        "\"scope\":\"private|project|team\",\"description\":\"...\",\"body\":\"...\",\"tags\":[\"...\"]}]}"
    )


def apply_extraction_records(cwd: str | Path, records: tuple[ExtractionRecord, ...]) -> ExtractionResult:
    """Write accepted records to durable memory."""

    written: list[Path] = []
    for record in records:
        if record.scope == "team":
            secret_error = check_team_memory_secrets(record.body)
            if secret_error:
                log.warning("memory extraction skipped team record %r: %s", record.title, secret_error)
                continue
            path, error = validate_team_memory_write_path(cwd, f"{record.title}.md")
            if error or path is None:
                log.warning("memory extraction skipped team record %r: %s", record.title, error)
                continue
        written.append(
            add_memory_entry(
                cwd,
                record.title,
                record.body,
                memory_type=record.memory_type,
                scope=record.scope,
                description=record.description,
                tags=record.tags,
            )
        )
    return ExtractionResult(
        skipped=not bool(written),
        reason="" if written else "all records rejected",
        records=records,
        written_paths=tuple(written),
    )


def _summarize_message(message: ConversationMessage) -> str:
    text = " ".join(message.text.split())
    if text:
        return f"{message.role}: {text[:1200]}"
    if message.tool_uses:
        return f"{message.role}: tool calls -> {', '.join(block.name for block in message.tool_uses)}"
    return f"{message.role}: [non-text content]"
