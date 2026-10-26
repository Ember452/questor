"""Tool for asking the interactive user a follow-up question."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from pydantic import BaseModel, Field

from questorharness.capabilities.tools.contract import ToolCapabilities, BaseTool, ToolExecutionContext, ToolResult


AskUserPrompt = Callable[[str, "list[str] | None"], Awaitable[str]]


class AskUserQuestionToolInput(BaseModel):
    """Arguments for asking the user a question."""

    question: str = Field(description="The exact question to ask the user")
    options: list[str] | None = Field(
        default=None,
        description=(
            "候选选项（可选）。给了选项时用户可按序号或原文回答；"
            "不给就是自由文本提问。选项只是提示，客户端仍会把回答原样回传。"
        ),
    )


class AskUserQuestionTool(BaseTool):
    """Ask the interactive user a question and return the answer."""

    name = "ask_user_question"
    description = "Ask the interactive user a follow-up question and return the answer."
    input_model = AskUserQuestionToolInput

    capabilities = ToolCapabilities()

    def is_read_only(self, arguments: AskUserQuestionToolInput) -> bool:
        del arguments
        return True

    async def execute(
        self,
        arguments: AskUserQuestionToolInput,
        context: ToolExecutionContext,
    ) -> ToolResult:
        prompt = context.metadata.get("ask_user_prompt")
        if not callable(prompt):
            return ToolResult(
                output="ask_user_question is unavailable in this session",
                is_error=True,
            )
        answer = str(await prompt(arguments.question, arguments.options)).strip()
        if not answer:
            return ToolResult(output="(no response)")
        return ToolResult(output=answer)

# questor: allow R7 -- until W8 adds the mirror test
