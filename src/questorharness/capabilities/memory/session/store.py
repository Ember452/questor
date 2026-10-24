"""Where session memory lives on disk, and how it is read and written.

Moved out of ``memory/session/__init__.py`` by plan 01 W8. Rendering the
checkpoint text lives in :mod:`document`.
"""

from __future__ import annotations

from hashlib import sha1
from pathlib import Path

from questorharness.capabilities.memory.session.document import build_session_memory_document
from questorharness.contracts.domain.message import ConversationMessage
from questorharness.platform.io import atomic_write_text
from questorharness.platform.paths import get_data_dir


def get_session_memory_dir(cwd: str | Path) -> Path:
    """Return the project session-memory directory."""

    root = Path(cwd).resolve()
    digest = sha1(str(root).encode("utf-8")).hexdigest()[:12]
    path = get_data_dir() / "session-memory" / f"{root.name}-{digest}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_session_memory_path(cwd: str | Path, session_id: str | None = None) -> Path:
    """Return the markdown session-memory path."""

    safe_session = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in (session_id or "default"))
    return get_session_memory_dir(cwd) / f"{safe_session or 'default'}.md"


def prepare_session_memory_metadata(
    cwd: str | Path,
    tool_metadata: dict[str, object],
    *,
    session_id: str | None = None,
) -> Path:
    """Ensure metadata points compaction to the session-memory file."""

    sid = session_id or str(tool_metadata.get("session_id") or "default")
    path = get_session_memory_path(cwd, sid)
    tool_metadata["session_memory_path"] = str(path)
    return path


def get_session_memory_content(path: str | Path | None) -> str:
    """Read session memory content if available."""

    if not path:
        return ""
    candidate = Path(path).expanduser()
    if not candidate.exists():
        return ""
    try:
        return candidate.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def update_session_memory_file(
    cwd: str | Path,
    messages: list[ConversationMessage],
    *,
    tool_metadata: dict[str, object] | None = None,
    session_id: str | None = None,
) -> Path:
    """Update the deterministic session-memory checkpoint."""

    path = prepare_session_memory_metadata(cwd, tool_metadata or {}, session_id=session_id)
    body = build_session_memory_document(messages, tool_metadata=tool_metadata)
    atomic_write_text(path, body)
    return path
