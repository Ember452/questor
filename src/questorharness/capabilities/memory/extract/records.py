"""Structured records produced by a memory extraction pass.

Moved out of ``memory/extract/__init__.py`` by plan 01 W8: parsing model output
into records is one concern; running the pass is another.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from questorharness.capabilities.memory.schema import (
    DEFAULT_MEMORY_SCOPE,
    DEFAULT_MEMORY_TYPE,
    MemoryScope,
    MemoryType,
    parse_memory_scope,
    parse_memory_type,
)


@dataclass(frozen=True)
class ExtractionRecord:
    """Structured memory record proposed by the extraction pass."""

    title: str
    body: str
    memory_type: MemoryType = DEFAULT_MEMORY_TYPE
    scope: MemoryScope = DEFAULT_MEMORY_SCOPE
    description: str = ""
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExtractionResult:
    """Outcome of a durable memory extraction run."""

    skipped: bool
    reason: str = ""
    records: tuple[ExtractionRecord, ...] = ()
    written_paths: tuple[Path, ...] = ()


def parse_extraction_records(text: str, *, max_records: int = 3) -> tuple[ExtractionRecord, ...]:
    """Parse JSON memory extraction output."""

    try:
        payload = json.loads(_extract_json_object(text))
    except json.JSONDecodeError:
        return ()
    raw_records = payload.get("memories") if isinstance(payload, dict) else None
    if not isinstance(raw_records, list):
        return ()
    records: list[ExtractionRecord] = []
    for item in raw_records[:max_records]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        body = str(item.get("body") or "").strip()
        if not title or not body:
            continue
        memory_type = parse_memory_type(item.get("type"), default=DEFAULT_MEMORY_TYPE) or DEFAULT_MEMORY_TYPE
        scope = parse_memory_scope(item.get("scope"), default=DEFAULT_MEMORY_SCOPE) or DEFAULT_MEMORY_SCOPE
        tags_raw = item.get("tags") or ()
        tags = tuple(str(tag).strip() for tag in tags_raw if str(tag).strip()) if isinstance(tags_raw, list) else ()
        records.append(
            ExtractionRecord(
                title=title,
                body=body,
                memory_type=memory_type,
                scope=scope,
                description=str(item.get("description") or "").strip(),
                tags=tags,
            )
        )
    return tuple(records)


def _extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return stripped[start : end + 1]
    return stripped
