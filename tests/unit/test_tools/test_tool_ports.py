"""Tool execution contexts receive sandbox and LLM ports by injection."""

from __future__ import annotations

from pathlib import Path

import pytest

from questorharness.capabilities.tools.base import ToolExecutionContext
from questorharness.capabilities.tools.fs.file_read_tool import FileReadTool, FileReadToolInput
from questorharness.capabilities.tools.media.image_to_text_tool import (
    ImageToTextTool,
    ImageToTextToolInput,
)


class _DenySandbox:
    """Sandbox runtime that rejects every path."""

    def is_active(self) -> bool:
        return True

    def validate_path(self, path: Path, cwd: Path) -> tuple[bool, str]:
        del path, cwd
        return False, "outside the sandbox boundary"

    def session(self):
        return None


class _FakeLlmRuntime:
    """LLM runtime that records the describe call."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def describe_image(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return "a described image"


@pytest.mark.asyncio
async def test_file_read_uses_injected_sandbox(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    target.write_text("hello", encoding="utf-8")

    tool = FileReadTool()
    result = await tool.execute(
        FileReadToolInput(path=str(target)),
        ToolExecutionContext(cwd=tmp_path, sandbox=_DenySandbox()),
    )

    assert result.is_error
    assert result.output.startswith("Sandbox:")


@pytest.mark.asyncio
async def test_image_to_text_uses_injected_llm_runtime(tmp_path: Path) -> None:
    llm = _FakeLlmRuntime()
    tool = ImageToTextTool()
    result = await tool.execute(
        ImageToTextToolInput(image_data="aGVsbG8="),
        ToolExecutionContext(
            cwd=tmp_path,
            metadata={"vision_model_config": {"model": "vision-model", "api_key": "test-key"}},
            llm=llm,
        ),
    )

    assert not result.is_error
    assert "a described image" in result.output
    assert llm.calls and llm.calls[0]["model"] == "vision-model"
