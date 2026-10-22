"""The tools package facade must not eagerly import every tool module."""

from __future__ import annotations

import importlib
import sys


def test_tools_facade_is_lazy() -> None:
    for name in list(sys.modules):
        if name == "questorharness.capabilities.tools" or name.startswith(
            "questorharness.capabilities.tools."
        ):
            sys.modules.pop(name)

    module = importlib.import_module("questorharness.capabilities.tools")
    loaded = [
        name
        for name in sys.modules
        if name.startswith("questorharness.capabilities.tools.")
    ]
    assert len(loaded) < 10, loaded

    factory = module.create_default_tool_registry
    assert callable(factory)

    loaded_after = [
        name
        for name in sys.modules
        if name.startswith("questorharness.capabilities.tools.")
    ]
    assert len(loaded_after) >= 30, loaded_after
