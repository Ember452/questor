"""Built-in tool registration."""

from questorharness.capabilities.tools.agent.ask_user_question_tool import AskUserQuestionTool
from questorharness.capabilities.tools.agent.agent_tool import AgentTool
from questorharness.capabilities.tools.shell.bash_tool import BashTool
from questorharness.capabilities.tools.base import BaseTool, ToolExecutionContext, ToolRegistry, ToolResult
from questorharness.capabilities.tools.brief_tool import BriefTool
from questorharness.capabilities.tools.config_tool import ConfigTool
from questorharness.capabilities.tools.cron.cron_create_tool import CronCreateTool
from questorharness.capabilities.tools.cron.cron_delete_tool import CronDeleteTool
from questorharness.capabilities.tools.cron.cron_list_tool import CronListTool
from questorharness.capabilities.tools.cron.cron_toggle_tool import CronToggleTool
from questorharness.capabilities.tools.enter_plan_mode_tool import EnterPlanModeTool
from questorharness.capabilities.tools.enter_worktree_tool import EnterWorktreeTool
from questorharness.capabilities.tools.exit_plan_mode_tool import ExitPlanModeTool
from questorharness.capabilities.tools.exit_worktree_tool import ExitWorktreeTool
from questorharness.capabilities.tools.fs.file_edit_tool import FileEditTool
from questorharness.capabilities.tools.fs.file_read_tool import FileReadTool
from questorharness.capabilities.tools.fs.file_write_tool import FileWriteTool
from questorharness.capabilities.tools.fs.glob_tool import GlobTool
from questorharness.capabilities.tools.fs.grep_tool import GrepTool
from questorharness.capabilities.tools.media.image_generation_tool import ImageGenerationTool
from questorharness.capabilities.tools.media.image_to_text_tool import ImageToTextTool
from questorharness.capabilities.tools.mcp.list_mcp_resources_tool import ListMcpResourcesTool
from questorharness.capabilities.tools.fs.lsp_tool import LspTool
from questorharness.capabilities.tools.mcp.mcp_auth_tool import McpAuthTool
from questorharness.capabilities.tools.mcp.mcp_tool import McpToolAdapter
from questorharness.capabilities.tools.fs.notebook_edit_tool import NotebookEditTool
from questorharness.capabilities.tools.mcp.read_mcp_resource_tool import ReadMcpResourceTool
from questorharness.capabilities.tools.remote_trigger_tool import RemoteTriggerTool
from questorharness.capabilities.tools.agent.send_message_tool import SendMessageTool
from questorharness.capabilities.tools.skill_tool import SkillTool
from questorharness.capabilities.tools.shell.sleep_tool import SleepTool
from questorharness.capabilities.tools.task.task_create_tool import TaskCreateTool
from questorharness.capabilities.tools.task.task_get_tool import TaskGetTool
from questorharness.capabilities.tools.task.task_list_tool import TaskListTool
from questorharness.capabilities.tools.task.task_output_tool import TaskOutputTool
from questorharness.capabilities.tools.task.task_stop_tool import TaskStopTool
from questorharness.capabilities.tools.task.task_update_tool import TaskUpdateTool
from questorharness.capabilities.tools.agent.team_create_tool import TeamCreateTool
from questorharness.capabilities.tools.agent.team_delete_tool import TeamDeleteTool
from questorharness.capabilities.tools.todo_write_tool import TodoWriteTool
from questorharness.capabilities.tools.agent.tool_search_tool import ToolSearchTool
from questorharness.capabilities.tools.web.web_fetch_tool import WebFetchTool
from questorharness.capabilities.tools.web.web_search_tool import WebSearchTool


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
