"""Turn a user-supplied name into one safe filename component.

Used when a channel receives an attachment whose name comes from the other side of the
network, so the value must never become a path. Replaces the ``helpers`` module this came
out of (plan 01 ledger #127): the file is named after what it does, and the only
in-repository caller is the Feishu adapter.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from pathlib import Path

__all__ = ["dedupe_filename", "safe_filename"]


def safe_filename(value: object, *, max_length: int = 128) -> str:
    """Return a conservative filename-safe representation of ``value``.

    Path separators, control characters, shell metacharacters, and whitespace
    collapse to underscores; Unicode word characters (CJK included) survive,
    because Chinese attachment names are the common case on Feishu, not an
    attack. The result is a single basename, not a path.
    """

    if value is None:
        return ""
    name = Path(str(value)).name
    name = unicodedata.normalize("NFKC", name)
    name = re.sub(r"[^\w.-]+", "_", name, flags=re.UNICODE).strip("_.-")
    if not name or name in {".", ".."}:
        return ""
    return name[:max_length]


def dedupe_filename(name: str, *, exists: Callable[[str], bool]) -> str:
    """Return ``name``, or ``name-N``, for the first candidate that does not exist.

    Two attachments in one message can carry the same sanitised name; the caller
    decides existence (usually ``(directory / candidate).exists()``) so the
    function stays pure and testable.
    """

    if not exists(name):
        return name
    stem, dot, extension = name.rpartition(".")
    if not dot or not stem:
        stem, extension = name, ""
    index = 1
    while index < 1000:
        candidate = f"{stem}-{index}.{extension}" if extension else f"{stem}-{index}"
        if not exists(candidate):
            return candidate
        index += 1
    return f"{stem}-999.{extension}" if extension else f"{stem}-999"

