"""The tools package facade must not eagerly import every tool module."""

from __future__ import annotations

import subprocess
import sys

_CODE = """
import sys
import questorharness.capabilities.tools as tools

prefix = "questorharness.capabilities.tools."
before = len([name for name in sys.modules if name.startswith(prefix)])
factory = tools.create_default_tool_registry
after = len([name for name in sys.modules if name.startswith(prefix)])
print(before, after, callable(factory))
"""


def test_tools_facade_is_lazy() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _CODE],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    before, after, callable_flag = result.stdout.split()
    assert int(before) < 10, result.stdout
    assert int(after) >= 30, result.stdout
    assert callable_flag == "True"
