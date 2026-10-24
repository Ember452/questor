"""Agent definition projection shared with capabilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class AgentProfile:
    """The subset of an agent definition a tool needs to launch it."""

    name: str
    model: str | None = None
    system_prompt: str | None = None
    permissions: list[str] = field(default_factory=list)


class AgentDefinition(BaseModel):
    """Full agent definition with all configuration fields.

    Field mapping to TypeScript ``BaseAgentDefinition``:
    - ``name``          → ``agentType``
    - ``description``   → ``whenToUse``
    - ``system_prompt`` → ``getSystemPrompt()`` return value
    - ``tools``         → ``tools`` (None means all tools / ``['*']``)
    - ``disallowed_tools`` → ``disallowedTools``
    - ``skills``        → ``skills``
    - ``mcp_servers``   → ``mcpServers``
    - ``hooks``         → ``hooks``
    - ``color``         → ``color``
    - ``model``         → ``model``
    - ``effort``        → ``effort``
    - ``permission_mode`` → ``permissionMode``
    - ``max_turns``     → ``maxTurns``
    - ``filename``      → ``filename``
    - ``base_dir``      → ``baseDir``
    - ``critical_system_reminder`` → ``criticalSystemReminder_EXPERIMENTAL``
    - ``required_mcp_servers`` → ``requiredMcpServers``
    - ``background``    → ``background``
    - ``initial_prompt`` → ``initialPrompt``
    - ``memory``        → ``memory``
    - ``isolation``     → ``isolation``
    - ``omit_claude_md`` → ``omitClaudeMd``
    """

    # --- 必填 ---
    name: str
    description: str

    # --- 提示词 / 工具 ---
    system_prompt: str | None = None
    tools: list[str] | None = None  # None 表示允许全部工具；['*'] 等价
    disallowed_tools: list[str] | None = None

    # --- 模型与投入等级 ---
    model: str | None = None  # 模型覆盖；None 表示继承默认值
    effort: str | int | None = None  # "low" | "medium" | "high" 或正整数

    # --- 权限 ---
    permission_mode: str | None = None  # PERMISSION_MODES 之一

    # --- Agent 循环控制 ---
    max_turns: int | None = None  # 停止前最大 Agent 轮次；必须 > 0

    # --- 技能与 MCP ---
    skills: list[str] = Field(default_factory=list)
    mcp_servers: list[Any] | None = None  # 字符串引用或 {name: config} 字典
    required_mcp_servers: list[str] | None = None  # 必须存在的服务器名称模式

    # --- 钩子 ---
    hooks: dict[str, Any] | None = None  # Agent 启动时注册的会话级钩子

    # --- 界面 ---
    color: str | None = None  # AGENT_COLORS 之一

    # --- 生命周期 ---
    background: bool = False  # 生成时始终作为后台任务运行
    initial_prompt: str | None = None  # 附加到第一个用户轮次之前
    memory: str | None = None  # MEMORY_SCOPES 之一
    isolation: str | None = None  # ISOLATION_MODES 之一

    # --- 元数据 ---
    filename: str | None = None  # 不含 .md 扩展名的原始文件名
    base_dir: str | None = None  # 加载 Agent 定义的目录
    critical_system_reminder: str | None = None  # 每个用户轮次重新注入的短消息
    pending_snapshot_update: dict[str, Any] | None = None  # 用于记忆快照跟踪
    omit_claude_md: bool = False  # 为此 Agent 跳过 CLAUDE.md 注入

    # --- Python 专用 ---
    permissions: list[str] = Field(default_factory=list)  # 额外权限规则
    subagent_type: str = "general-purpose"  # 运行时使用的路由键
    source: Literal["builtin", "user", "plugin"] = "builtin"

# questor: allow R7 -- until W8 adds the mirror test
