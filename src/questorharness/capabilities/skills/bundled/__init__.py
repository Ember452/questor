"""Bundled skill definitions loaded from .md files.

Facade only (ADR-0003 §2): the discovery behavior lives in ``discovery.py``.
"""

from __future__ import annotations

from questorharness.capabilities.skills.bundled.discovery import get_bundled_skills

__all__ = ["get_bundled_skills"]
