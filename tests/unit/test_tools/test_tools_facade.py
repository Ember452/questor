"""The tools package facade must stay lazy until the factory is actually called."""

from __future__ import annotations

import subprocess
import sys

_CODE = """
import sys
import questorharness.capabilities.tools as tools

prefix = "questorharness.capabilities.tools."
before = len([name for name in sys.modules if name.startswith(prefix)])
factory = tools.create_default_tool_registry
# Merely touching the factory must not import 40 tool modules: discovery happens
# on the first call, which is what keeps cold imports cheap.
middle = len([name for name in sys.modules if name.startswith(prefix)])
registry = factory(None)
after = len([name for name in sys.modules if name.startswith(prefix)])
print(before, middle, after, len(registry.list_tools()), callable(factory))
"""


def test_tools_facade_is_lazy() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _CODE],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    before, middle, after, tool_count, callable_flag = result.stdout.split()
    assert int(before) < 10, result.stdout
    assert int(middle) < 10, result.stdout
    assert int(after) >= 30, result.stdout
    assert int(tool_count) >= 30, result.stdout
    assert callable_flag == "True"
