"""Small text helpers shared by the autopilot store and its mixins."""

from __future__ import annotations

from pathlib import Path


def _shorten(text: str, *, limit: int = 120) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def _safe_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _json_default(value: object) -> object:
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _bilingual_lines(zh: str, en: str) -> str:
    return f"{zh}\n{en}".strip()
