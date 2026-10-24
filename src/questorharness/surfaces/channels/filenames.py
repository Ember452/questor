"""Turn a user-supplied name into one safe filename component.

Used when a channel receives an attachment whose name comes from the other side of the
network, so the value must never become a path. Replaces the ``helpers`` module this came
out of (plan 01 ledger #127): the file is named after what it does, and the only
in-repository caller is the Feishu adapter.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

__all__ = ["safe_filename"]


def safe_filename(value: object, *, max_length: int = 128) -> str:
    """Return a conservative filename-safe representation of ``value``.

    Path separators, control characters, shell metacharacters, and whitespace
    collapse to underscores. The result is a single basename, not a path.
    """

    if value is None:
        return ""
    name = Path(str(value)).name
    name = unicodedata.normalize("NFKC", name)
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._-")
    if not name or name in {".", ".."}:
        return ""
    return name[:max_length]
