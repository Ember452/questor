"""Built-in tool registration."""

from questorharness.tools.ask_user_question_tool import AskUserQuestionTool
from questorharness.tools.agent_tool import AgentTool
from questorharness.tools.bash_tool import BashTool
from questorharness.tools.base import BaseTool, ToolExecutionContext, ToolRegistry, ToolResult
from questorharness.tools.brief_tool import BriefTool
from questorharness.tools.config_tool import ConfigTool
from questorharness.tools.cron_create_tool import CronCreateTool
from questorharness.tools.cron_delete_tool import CronDeleteTool
from questorharness.tools.cron_list_tool import CronListTool
from questorharness.tools.cron_toggle_tool import CronToggleTool
from questorharness.tools.enter_plan_mode_tool import EnterPlanModeTool
from questorharness.tools.enter_worktree_tool import EnterWorktreeTool
from questorharness.tools.exit_plan_mode_tool import ExitPlanModeTool
from questorharness.tools.exit_worktree_tool import ExitWorktreeTool
from questorharness.tools.file_edit_tool import FileEditTool
from questorharness.tools.file_read_tool import FileReadTool
from questorharness.tools.file_write_tool import FileWriteTool
from questorharness.tools.glob_tool import GlobTool
from questorharness.tools.grep_tool import GrepTool
from questorharness.tools.image_generation_tool import ImageGenerationTool
from questorharness.tools.image_to_text_tool import ImageToTextTool
from questorharness.tools.list_mcp_resources_tool import ListMcpResourcesTool
from questorharness.tools.lsp_tool import LspTool
from questorharness.tools.mcp_auth_tool import McpAuthTool
from questorharness.tools.mcp_tool import McpToolAdapter
from questorharness.tools.notebook_edit_tool import NotebookEditTool
from questorharness.tools.read_mcp_resource_tool import ReadMcpResourceTool
from questorharness.tools.remote_trigger_tool import RemoteTriggerTool
from questorharness.tools.send_message_tool import SendMessageTool
from questorharness.tools.skill_tool import SkillTool
from questorharness.tools.sleep_tool import SleepTool
from questorharness.tools.task_create_tool import TaskCreateTool
from questorharness.tools.task_get_tool import TaskGetTool
from questorharness.tools.task_list_tool import TaskListTool
from questorharness.tools.task_output_tool import TaskOutputTool
from questorharness.tools.task_stop_tool import TaskStopTool
from questorharness.tools.task_update_tool import TaskUpdateTool
from questorharness.tools.team_create_tool import TeamCreateTool
from questorharness.tools.team_delete_tool import TeamDeleteTool
from questorharness.tools.todo_write_tool import TodoWriteTool
from questorharness.tools.tool_search_tool import ToolSearchTool
from questorharness.tools.web_fetch_tool import WebFetchTool
from questorharness.tools.web_search_tool import WebSearchTool


def create_default_tool_registry(mcp_manager=None) -> ToolRegistry:
    """Return the default built-in tool registry."""
    registry = ToolRegistry()
    for tool in (
        BashTool(),
        AskUserQuestionTool(),
        FileReadTool(),
        FileWriteTool(),
        FileEditTool(),
        NotebookEditTool(),
        LspTool(),
        McpAuthTool(),
        GlobTool(),
        GrepTool(),
        ImageToTextTool(),
        ImageGenerationTool(),
        SkillTool(),
        ToolSearchTool(),
        WebFetchTool(),
        WebSearchTool(),
        ConfigTool(),
        BriefTool(),
        SleepTool(),
        EnterWorktreeTool(),
        ExitWorktreeTool(),
        TodoWriteTool(),
        EnterPlanModeTool(),
        ExitPlanModeTool(),
        CronCreateTool(),
        CronListTool(),
        CronDeleteTool(),
        CronToggleTool(),
        RemoteTriggerTool(),
        TaskCreateTool(),
        TaskGetTool(),
        TaskListTool(),
        TaskStopTool(),
        TaskOutputTool(),
        TaskUpdateTool(),
        AgentTool(),
        SendMessageTool(),
        TeamCreateTool(),
        TeamDeleteTool(),
    ):
        registry.register(tool)
    if mcp_manager is not None:
        registry.register(ListMcpResourcesTool(mcp_manager))
        registry.register(ReadMcpResourceTool(mcp_manager))
        for tool_info in mcp_manager.list_tools():
            registry.register(McpToolAdapter(mcp_manager, tool_info))
    return registry


__all__ = [
    "BaseTool",
    "ToolExecutionContext",
    "ToolRegistry",
    "ToolResult",
    "create_default_tool_registry",
]
