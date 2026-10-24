"""File-backed session memory for compact continuity.

Facade only (ADR-0003 §2): disk access lives in ``store``, the checkpoint text in
``document``.
"""

from __future__ import annotations

from questorharness.capabilities.memory.session.document import (
    MAX_RECENT_LINES,
    MAX_SESSION_MEMORY_CHARS,
    build_session_memory_document,
    session_memory_to_compact_text,
)
from questorharness.capabilities.memory.session.store import (
    get_session_memory_content,
    get_session_memory_dir,
    get_session_memory_path,
    prepare_session_memory_metadata,
    update_session_memory_file,
)

__all__ = [
    "MAX_RECENT_LINES",
    "MAX_SESSION_MEMORY_CHARS",
    "build_session_memory_document",
    "get_session_memory_content",
    "get_session_memory_dir",
    "get_session_memory_path",
    "prepare_session_memory_metadata",
    "session_memory_to_compact_text",
    "update_session_memory_file",
]
