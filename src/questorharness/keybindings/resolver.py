"""Keybinding resolution."""

from __future__ import annotations

from questorharness.keybindings.default_bindings import DEFAULT_KEYBINDINGS


def resolve_keybindings(overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Merge user overrides over the default keybindings."""
    resolved = dict(DEFAULT_KEYBINDINGS)
    if overrides:
        resolved.update(overrides)
    return resolved

# questor: allow R7 -- until W8 adds the mirror test
