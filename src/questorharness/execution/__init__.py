"""Process and network execution primitives.

Subprocess spawning (with sandbox wrapping) and guarded HTTP fetching. These sit
above ``providers``/``config`` because they need the sandbox adapter and the web
settings, and below ``runtime``/``capabilities`` because both layers execute
commands and fetch URLs. ``platform`` stays dependency-free underneath.
"""

from __future__ import annotations
