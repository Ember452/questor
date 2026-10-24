"""Mirror test for ``capabilities/tools/contract.py`` (plan 01, R7).

Scope note: the individual tools are covered by the many ``test_*_tool.py`` files, and
``check_tool_radius.py`` guards that each tool *declares* capabilities. What had no
test was the contract itself — the assumptions every tool and every caller inherit:
that an unspecified capability means "not allowed", that a tool that does not say
otherwise is treated as writing, and that the registry keys on the tool's own name.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from pydantic import BaseModel

from questorharness.capabilities.tools.contract import (
    BaseTool,
    ToolCapabilities,
    ToolExecutionContext,
    ToolRegistry,
    ToolResult,
)


class _Input(BaseModel):
    text: str = "hello"


class _Echo(BaseTool):
    name = "echo"
    description = "Return the argument"
    input_model = _Input
    capabilities = ToolCapabilities(read_only_by_default=True)

    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
        return ToolResult(output=str(getattr(arguments, "text", "")))


class _Writer(BaseTool):
    name = "write"
    description = "Touch the filesystem"
    input_model = _Input
    capabilities = ToolCapabilities()

    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
        return ToolResult(output="wrote", is_error=True)


def test_an_unstated_capability_defaults_to_the_safe_answer() -> None:
    caps = ToolCapabilities()

    assert caps.read_only_by_default is False
    assert caps.keep_in_compaction is False
    assert caps.artifact_keys == ()
    assert caps.remember_as is None


def test_capabilities_cannot_be_mutated_after_declaration() -> None:
    caps = ToolCapabilities()

    with pytest.raises(FrozenInstanceError):
        caps.keep_in_compaction = True  # type: ignore[misc]


def test_a_tool_that_does_not_declare_read_only_is_treated_as_writing() -> None:
    assert _Writer().is_read_only(_Input()) is False
    assert _Writer.capabilities.read_only_by_default is False


def test_base_tool_refuses_to_be_instantiated_without_execute() -> None:
    class _Incomplete(BaseTool):
        name = "incomplete"
        description = "no execute"
        input_model = _Input
        capabilities = ToolCapabilities()

    with pytest.raises(TypeError):
        _Incomplete()


def test_api_schema_carries_name_description_and_json_input() -> None:
    schema = _Echo().to_api_schema()

    assert schema["name"] == "echo"
    assert schema["description"] == "Return the argument"
    assert schema["input_schema"]["properties"]["text"]["default"] == "hello"


def test_execution_context_isolated_mutable_defaults() -> None:
    first = ToolExecutionContext(cwd=Path("/tmp/a"))
    second = ToolExecutionContext(cwd=Path("/tmp/b"))

    first.metadata["k"] = "v"
    assert second.metadata == {}
    assert first.hook_executor is None
    assert first.sandbox is None
    assert first.llm is None
    assert first.lsp is None
    assert first.tasks is None
    assert first.subagents is None


def test_tool_result_is_success_unless_it_says_otherwise() -> None:
    ok = ToolResult(output="done")
    failed = ToolResult(output="nope", is_error=True, metadata={"code": 2})

    assert ok.is_error is False
    assert ok.metadata == {}
    assert failed.is_error is True
    assert failed.metadata == {"code": 2}


def test_registry_keys_on_the_tools_own_declared_name() -> None:
    registry = ToolRegistry()
    echo = _Echo()

    registry.register(echo)

    assert registry.get("echo") is echo
    assert registry.get("missing") is None
    assert registry.list_tools() == [echo]


def test_registering_the_same_name_twice_replaces_the_first() -> None:
    registry = ToolRegistry()
    registry.register(_Echo())

    class _RenamedEcho(_Echo):
        name = "echo"
        description = "Second implementation wins"

    registry.register(_RenamedEcho())

    assert len(registry.list_tools()) == 1
    assert registry.get("echo").description == "Second implementation wins"


def test_registry_schema_list_follows_registration_order() -> None:
    registry = ToolRegistry()
    registry.register(_Writer())
    registry.register(_Echo())

    schemas = registry.to_api_schema()

    assert [entry["name"] for entry in schemas] == ["write", "echo"]
    assert all(set(entry) == {"name", "description", "input_schema"} for entry in schemas)


async def test_context_ports_reach_the_tool() -> None:
    registry = ToolRegistry()
    registry.register(_Echo())
    context = ToolExecutionContext(cwd=Path("/tmp"), metadata={"session": "s-1"})

    result = await registry.get("echo").execute(_Input(text="hi"), context)

    assert result == ToolResult(output="hi")
