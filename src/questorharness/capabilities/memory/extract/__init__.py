"""Durable memory extraction from completed turns.

Facade only (ADR-0003 §2): records live in ``records``, agent permissions in
``guard``, and the pass itself in ``extraction``.
"""

from __future__ import annotations

from questorharness.capabilities.memory.extract.extraction import (
    EXTRACTION_SYSTEM_PROMPT,
    apply_extraction_records,
    build_extraction_prompt,
    extract_memories_from_turn,
)
from questorharness.capabilities.memory.extract.guard import (
    has_memory_writes_since,
    validate_extraction_tool_request,
)
from questorharness.capabilities.memory.extract.records import (
    ExtractionRecord,
    ExtractionResult,
    parse_extraction_records,
)

__all__ = [
    "EXTRACTION_SYSTEM_PROMPT",
    "ExtractionRecord",
    "ExtractionResult",
    "apply_extraction_records",
    "build_extraction_prompt",
    "extract_memories_from_turn",
    "has_memory_writes_since",
    "parse_extraction_records",
    "validate_extraction_tool_request",
]
