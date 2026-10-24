"""Local rules file management."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

_RULES_DIR = Path("~/.questorharness/local_rules").expanduser()
_RULES_FILE = _RULES_DIR / "rules.md"
_FACTS_FILE = _RULES_DIR / "facts.json"


def _ensure_dir() -> None:
    _RULES_DIR.mkdir(parents=True, exist_ok=True)


def load_local_rules() -> str:
    """Load the local rules markdown, or empty string if none exist."""
    if _RULES_FILE.exists():
        return _RULES_FILE.read_text(encoding="utf-8").strip()
    return ""


def save_local_rules(content: str) -> Path:
    """Write local rules markdown."""
    _ensure_dir()
    _RULES_FILE.write_text(content.strip() + "\n", encoding="utf-8")
    return _RULES_FILE


def load_facts() -> dict:
    """Load extracted facts as a dict."""
    if _FACTS_FILE.exists():
        return json.loads(_FACTS_FILE.read_text(encoding="utf-8"))
    return {"facts": [], "last_updated": None}


def save_facts(facts: dict) -> None:
    """Persist extracted facts."""
    _ensure_dir()
    facts["last_updated"] = datetime.now(timezone.utc).isoformat()
    _FACTS_FILE.write_text(
        json.dumps(facts, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def merge_facts(existing: dict, new_facts: list[dict]) -> dict:
    """Merge new facts into existing, deduplicating by key.

    Stored entries are read from a file that a person or an older writer may have
    touched, so an entry whose key is missing or empty is kept verbatim instead of
    raising: one bad line must not break every later merge, and dropping the entry
    would trade a loud failure for silent memory loss. Keyed entries still collapse
    onto one slot, in the position the key was first seen (ledger #113).
    """
    merged: list[dict] = []
    positions: dict[str, int] = {}
    for fact in existing.get("facts", []):
        key = fact.get("key")
        if not key:
            merged.append(fact)
            continue
        if key in positions:
            merged[positions[key]] = fact
            continue
        positions[key] = len(merged)
        merged.append(fact)
    for fact in new_facts:
        key = fact.get("key", "")
        if not key:
            continue
        if key in positions:
            # 用较新的值更新，保留较高置信度
            old = merged[positions[key]]
            if fact.get("confidence", 0) >= old.get("confidence", 0):
                merged[positions[key]] = fact
        else:
            positions[key] = len(merged)
            merged.append(fact)
    return {"facts": merged}
