"""R9: every tool input schema must stay enumerable.

A property whose JSON schema is a bare ``{}`` (what ``Any`` produces) tells the
model nothing about the value: no type, no reference, no enum. That is the
"model-visible surface" half of the layout rules; W3 covers the prompt surface.

The predicate lives here (not in ``check_layout``) because it needs imported
models, not a text scan.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, create_model

from questorharness.capabilities.tools.registry import create_default_tool_registry

ENUMERABLE_KEYS = frozenset({"type", "$ref", "anyOf", "enum", "const", "allOf"})
MINIMUM_TOOL_COUNT = 30


def enumerable_problems(model: type[BaseModel]) -> list[str]:
    """Return ``field: schema`` for every property that carries no type hint."""
    schema = model.model_json_schema()
    problems: list[str] = []
    for name, prop in (schema.get("properties") or {}).items():
        if not isinstance(prop, dict) or not (ENUMERABLE_KEYS & set(prop)):
            problems.append(f"{name}: {prop}")
    return problems


def test_registry_is_not_empty() -> None:
    """A guard that scans nothing must never pass (fail-on-empty)."""
    tools = create_default_tool_registry(None).list_tools()
    assert len(tools) >= MINIMUM_TOOL_COUNT, f"only {len(tools)} tools; R9 cannot pass vacuously"


def test_every_tool_property_is_enumerable() -> None:
    """No tool may expose a property the model cannot enumerate."""
    failures: list[str] = []
    for tool in create_default_tool_registry(None).list_tools():
        for problem in enumerable_problems(tool.input_model):
            failures.append(f"{tool.name}.{problem}")
    assert not failures, "bare schema properties:\n  " + "\n  ".join(failures)


def test_predicate_can_go_red() -> None:
    """The predicate itself must detect an ``Any`` field (proves it is a gate)."""
    loose = create_model("Loose", payload=(Any, ...))
    assert enumerable_problems(loose), "predicate failed to flag an Any field"
