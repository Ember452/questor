"""Import regression tests for swarm startup."""

from __future__ import annotations

import importlib
import sys


def test_create_default_tool_registry_does_not_import_mailbox_eagerly():
    for module_name in list(sys.modules):
        if module_name == "questorharness.capabilities.tools" or module_name.startswith("questorharness.capabilities.tools."):
            sys.modules.pop(module_name, None)
        if module_name == "questorharness.swarm" or module_name.startswith("questorharness.swarm."):
            sys.modules.pop(module_name, None)

    tools = importlib.import_module("questorharness.capabilities.tools")
    registry = tools.create_default_tool_registry()

    assert registry.get("bash") is not None
    assert "questorharness.swarm.mailbox" not in sys.modules
    assert "questorharness.swarm.lockfile" not in sys.modules
