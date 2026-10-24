"""Split one outbound channel message into provider-sized chunks.

The channel layer hits platform message-length limits, so chunking belongs here. Note the
second, **different** chunker in ``questor.gateway.notify._chunk_text`` (it prefers a
newline only past half the window and strips each chunk); the two are not interchangeable
and unifying them is a separate decision, not a detail of this move.
"""

from __future__ import annotations

__all__ = ["split_message"]


def split_message(text: str, max_length: int) -> list[str]:
    """Split text into chunks no longer than ``max_length`` characters.

    The splitter prefers newline and whitespace boundaries, but will hard-split
    long unbroken text. Empty input produces no chunks.
    """

    if max_length <= 0:
        raise ValueError("max_length must be positive")
    if not text:
        return []
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_length:
        split_at = remaining.rfind("\n", 0, max_length + 1)
        if split_at <= 0:
            split_at = remaining.rfind(" ", 0, max_length + 1)
        if split_at <= 0:
            split_at = max_length

        chunk = remaining[:split_at].rstrip()
        if not chunk:
            chunk = remaining[:max_length]
            split_at = max_length
        chunks.append(chunk)
        remaining = remaining[split_at:].lstrip()

    if remaining:
        chunks.append(remaining)
    return chunks
