"""`ask_user_question`：问题与选项都交给宿主提示，空答案按未回答处理。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from questorharness.capabilities.tools.agent.ask_user_question_tool import (
    AskUserQuestionTool,
    AskUserQuestionToolInput,
)


def _context(prompt: Any) -> Any:
    return SimpleNamespace(metadata={"ask_user_prompt": prompt})


def test_prompt_receives_question_and_options() -> None:
    """A2：宿主提示拿到 (question, options)，选项由客户端结构化呈现。"""

    seen: list[tuple[str, Any]] = []

    async def prompt(question: str, options: Any = None) -> str:
        seen.append((question, options))
        return "b"

    result = asyncio.run(
        AskUserQuestionTool().execute(
            AskUserQuestionToolInput(question="选哪个？", options=["a", "b"]),
            _context(prompt),
        )
    )
    assert seen == [("选哪个？", ["a", "b"])]
    assert result.output == "b"


def test_options_are_optional_and_default_to_none() -> None:
    """不带 options 的旧调用路径原样可用（additive 契约）。"""

    seen: list[tuple[str, Any]] = []

    async def prompt(question: str, options: Any = None) -> str:
        seen.append((question, options))
        return "ok"

    asyncio.run(
        AskUserQuestionTool().execute(AskUserQuestionToolInput(question="q"), _context(prompt))
    )
    assert seen == [("q", None)]


def test_blank_answer_is_reported_as_no_response() -> None:
    async def prompt(question: str, options: Any = None) -> str:
        return "   "

    result = asyncio.run(
        AskUserQuestionTool().execute(AskUserQuestionToolInput(question="q"), _context(prompt))
    )
    assert result.output == "(no response)"
