"""Voice mode keyterm extraction."""

from __future__ import annotations

import re


def extract_keyterms(text: str) -> list[str]:
    """Extract likely key terms from a transcript."""
    return sorted({token.lower() for token in re.findall(r"[A-Za-z0-9_]{4,}", text)})

# questor: allow R7 -- until W8 adds the mirror test
