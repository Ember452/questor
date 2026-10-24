"""Plugin discovery adapter for the ``PluginSource`` port.

``capabilities`` owns the port (it needs plugin skills while building the prompt)
but must not import ``plugins``; the assembly layer wires this adapter instead.
Keeping the adapter here means the direction is always ``plugins -> capabilities``
plus ``bootstrap -> plugins``, never ``capabilities -> plugins``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from questorharness.plugins.loader import load_plugins


class PluginLoaderSource:
    """The real plugin loader, exposed through the port."""

    def load(
        self,
        settings: Any,
        cwd: str | Path,
        *,
        extra_roots: Iterable[str | Path] | None = None,
    ) -> Sequence[Any]:
        """Return the plugins visible from ``cwd``."""
        return load_plugins(settings, str(cwd), extra_roots=extra_roots)


class NullPluginSource:
    """A source that finds no plugins. Used by snapshot tools and tests."""

    def load(
        self,
        settings: Any,
        cwd: str | Path,
        *,
        extra_roots: Iterable[str | Path] | None = None,
    ) -> Sequence[Any]:
        """Always return an empty plugin list."""
        del settings, cwd, extra_roots
        return []


def ensure_plugin_source() -> None:
    """Wire the real loader once; safe to call from every assembly entry point."""
    from questorharness.capabilities.skills.loader import (
        configure_plugin_source,
        plugin_source_configured,
    )

    if not plugin_source_configured():
        configure_plugin_source(PluginLoaderSource())