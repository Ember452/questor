"""Tool for leaving plan permission mode."""

from __future__ import annotations

from pydantic import BaseModel

from questorharness.config.settings import load_settings, save_settings
from questorharness.capabilities.policy import PermissionMode
from questorharness.capabilities.tools.base import ToolCapabilities, BaseTool, ToolExecutionContext, ToolResult


class ExitPlanModeToolInput(BaseModel):
    """No-op input model."""


class ExitPlanModeTool(BaseTool):
    """Switch settings permission mode back to default."""

    name = "exit_plan_mode"
    description = "Switch permission mode back to default."
    input_model = ExitPlanModeToolInput

    capabilities = ToolCapabilities(
        remember_as="plan_exit",
    )

    async def execute(self, arguments: ExitPlanModeToolInput, context: ToolExecutionContext) -> ToolResult:
        del arguments, context
        settings = load_settings()
        settings.permission.mode = PermissionMode.DEFAULT
        save_settings(settings)
        return ToolResult(output="Permission mode set to default")

# questor: allow R7 -- until W8 adds the mirror test
