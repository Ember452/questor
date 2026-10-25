# Namespace registries

<!-- generated skeleton by scripts/guards/gen_namespaces.py; consumers column is reviewed by hand -->

每个命名空间一张表：`name` 是模型/用户可见的名字，`producer` 是定义它的文件，
`consumers` 是读取它的文件（生成器填到前两个命中，人可以改）。
同一命名空间内名字唯一（大小写不敏感），表中每个路径都必须真实存在，
代码里出现的名字必须出现在表里——三条断言由 `scripts/guards/check_name_registries.py` 执行。

`—` 表示生成器没有找到第二个引用点，不是豁免。

## tool

共 43 条。

| name | producer | consumers |
| --- | --- | --- |
| McpToolAdapter | `src/questorharness/capabilities/tools/mcp/mcp_tool.py` | `src/questorharness/capabilities/tools/registry.py` |
| agent | `src/questorharness/capabilities/tools/agent/agent_tool.py` | `src/questor/__init__.py` / `src/questor/cli.py` |
| ask_user_question | `src/questorharness/capabilities/tools/agent/ask_user_question_tool.py` | — |
| bash | `src/questorharness/capabilities/tools/shell/bash_tool.py` | `src/questor/gateway/bridge.py` / `src/questorharness/capabilities/context/compact/limits.py` |
| brief | `src/questorharness/capabilities/tools/brief_tool.py` | `src/questorharness/capabilities/context/coordinator.py` / `src/questorharness/runtime/swarm/mailbox.py` |
| config | `src/questorharness/capabilities/tools/config_tool.py` | `src/questor/cli.py` / `src/questor/gateway/bridge.py` |
| cron_create | `src/questorharness/capabilities/tools/cron/cron_create_tool.py` | — |
| cron_delete | `src/questorharness/capabilities/tools/cron/cron_delete_tool.py` | — |
| cron_list | `src/questorharness/capabilities/tools/cron/cron_list_tool.py` | — |
| cron_toggle | `src/questorharness/capabilities/tools/cron/cron_toggle_tool.py` | — |
| edit_file | `src/questorharness/capabilities/tools/fs/file_edit_tool.py` | `src/questorharness/capabilities/context/compact/limits.py` / `src/questorharness/capabilities/context/compact/prompts.py` |
| enter_plan_mode | `src/questorharness/capabilities/tools/enter_plan_mode_tool.py` | `src/questorharness/engine/tool_metadata.py` |
| enter_worktree | `src/questorharness/capabilities/tools/enter_worktree_tool.py` | — |
| exit_plan_mode | `src/questorharness/capabilities/tools/exit_plan_mode_tool.py` | `src/questorharness/engine/tool_metadata.py` / `src/questorharness/runtime/coordinator/agent_definitions.py` |
| exit_worktree | `src/questorharness/capabilities/tools/exit_worktree_tool.py` | — |
| glob | `src/questorharness/capabilities/tools/fs/glob_tool.py` | `src/questor/session_storage.py` / `src/questorharness/capabilities/context/compact/limits.py` |
| grep | `src/questorharness/capabilities/tools/fs/grep_tool.py` | `src/questorharness/capabilities/context/compact/limits.py` / `src/questorharness/capabilities/context/compact/prompts.py` |
| image_generation | `src/questorharness/capabilities/tools/media/image_generation_tool.py` | `src/questor/gateway/media.py` / `src/questorharness/bootstrap/runtime.py` |
| image_to_text | `src/questorharness/capabilities/tools/media/image_to_text_tool.py` | `src/questorharness/config/settings_models.py` / `src/questorharness/engine/vision.py` |
| list_mcp_resources | `src/questorharness/capabilities/tools/mcp/list_mcp_resources_tool.py` | — |
| lsp | `src/questorharness/capabilities/tools/fs/lsp_tool.py` | `src/questorharness/capabilities/ports.py` / `src/questorharness/capabilities/tools/contract.py` |
| mcp_auth | `src/questorharness/capabilities/tools/mcp/mcp_auth_tool.py` | — |
| notebook_edit | `src/questorharness/capabilities/tools/fs/notebook_edit_tool.py` | `src/questorharness/runtime/coordinator/agent_definitions.py` |
| questor_create_feishu_group | `src/questor/gateway/group_tool.py` | `src/questor/gateway/bridge.py` / `src/questor/gateway/runtime.py` |
| read_file | `src/questorharness/capabilities/tools/fs/file_read_tool.py` | `src/questorharness/capabilities/context/compact/limits.py` / `src/questorharness/capabilities/context/compact/prompts.py` |
| read_mcp_resource | `src/questorharness/capabilities/tools/mcp/read_mcp_resource_tool.py` | — |
| remote_trigger | `src/questorharness/capabilities/tools/remote_trigger_tool.py` | — |
| send_message | `src/questorharness/capabilities/tools/agent/send_message_tool.py` | `src/questorharness/bootstrap/hosts/app.py` / `src/questorharness/capabilities/context/coordinator.py` |
| skill | `src/questorharness/capabilities/tools/skill_tool.py` | `src/questorharness/capabilities/context/compact/attachments.py` / `src/questorharness/capabilities/context/coordinator.py` |
| sleep | `src/questorharness/capabilities/tools/shell/sleep_tool.py` | `src/questor/gateway/gateway_process.py` / `src/questorharness/bootstrap/hosts/coordinator_drain.py` |
| task_create | `src/questorharness/capabilities/tools/task/task_create_tool.py` | `src/questorharness/capabilities/context/coordinator.py` |
| task_get | `src/questorharness/capabilities/tools/task/task_get_tool.py` | `src/questorharness/capabilities/context/coordinator.py` |
| task_list | `src/questorharness/capabilities/tools/task/task_list_tool.py` | `src/questorharness/capabilities/context/coordinator.py` |
| task_output | `src/questorharness/capabilities/tools/task/task_output_tool.py` | `src/questorharness/capabilities/context/coordinator.py` / `src/questorharness/capabilities/context/prompts/context.py` |
| task_stop | `src/questorharness/capabilities/tools/task/task_stop_tool.py` | `src/questorharness/capabilities/context/coordinator.py` |
| task_update | `src/questorharness/capabilities/tools/task/task_update_tool.py` | — |
| team_create | `src/questorharness/capabilities/tools/agent/team_create_tool.py` | — |
| team_delete | `src/questorharness/capabilities/tools/agent/team_delete_tool.py` | — |
| todo_write | `src/questorharness/capabilities/tools/todo_write_tool.py` | — |
| tool_search | `src/questorharness/capabilities/tools/agent/tool_search_tool.py` | — |
| web_fetch | `src/questorharness/capabilities/tools/web/web_fetch_tool.py` | `src/questorharness/capabilities/context/compact/limits.py` / `src/questorharness/capabilities/context/coordinator.py` |
| web_search | `src/questorharness/capabilities/tools/web/web_search_tool.py` | `src/questorharness/capabilities/context/compact/limits.py` / `src/questorharness/capabilities/context/coordinator.py` |
| write_file | `src/questorharness/capabilities/tools/fs/file_write_tool.py` | `src/questorharness/capabilities/context/compact/limits.py` / `src/questorharness/capabilities/context/compact/prompts.py` |

## command

共 68 条。

| name | producer | consumers |
| --- | --- | --- |
| agents | `src/questorharness/commands/families/agents.py` | `src/questorharness/capabilities/context/coordinator.py` / `src/questorharness/capabilities/context/prompts/context.py` |
| autopilot | `src/questorharness/commands/families/agents.py` | `src/questorharness/bootstrap/runtime.py` / `src/questorharness/bootstrap/cli/autopilot_commands.py` |
| branch | `src/questorharness/commands/families/project.py` | `src/questorharness/capabilities/context/coordinator.py` / `src/questorharness/capabilities/context/prompts/environment.py` |
| bridge | `src/questorharness/commands/families/workspace.py` | `src/questor/gateway/bridge.py` / `src/questor/gateway/gateway_process.py` |
| clear | `src/questorharness/commands/families/session.py` | `src/questor/gateway/provider_commands.py` / `src/questorharness/capabilities/context/compact/__init__.py` |
| commit | `src/questorharness/commands/families/project.py` | `src/questorharness/capabilities/context/coordinator.py` / `src/questorharness/bootstrap/cli/preview.py` |
| compact | `src/questorharness/commands/families/session.py` | `src/questor/gateway/media.py` / `src/questor/gateway/runtime.py` |
| config | `src/questorharness/commands/families/account.py` | `src/questor/cli.py` / `src/questor/gateway/bridge.py` |
| context | `src/questorharness/commands/families/session.py` | `src/questor/gateway/bridge.py` / `src/questor/gateway/group_tool.py` |
| continue | `src/questorharness/commands/families/model.py` | `src/questor/cli.py` / `src/questor/gateway/bridge.py` |
| copy | `src/questorharness/commands/families/workspace.py` | `src/questor/gateway/gateway_process.py` / `src/questor/runtime.py` |
| cost | `src/questorharness/commands/families/session.py` | `src/questorharness/bootstrap/cli/preview.py` |
| debug | `src/questorharness/commands/command_display.py` | `src/questorharness/capabilities/schedule/cron_scheduler.py` |
| diagnose | `src/questorharness/commands/command_display.py` | `src/questorharness/capabilities/context/prompts/system_prompt.py` |
| diff | `src/questorharness/commands/families/project.py` | `src/questorharness/capabilities/memory/consolidate/backup.py` |
| doctor | `src/questorharness/commands/families/diagnostics.py` | `src/questor/cli.py` / `src/questorharness/bootstrap/cli/preview.py` |
| dream | `src/questorharness/commands/families/memory.py` | `src/questorharness/capabilities/memory/consolidate/__init__.py` / `src/questorharness/capabilities/memory/consolidate/backup.py` |
| effort | `src/questorharness/commands/families/model.py` | `src/questorharness/bootstrap/hosts/app.py` |
| exit | `src/questorharness/commands/families/session.py` | `src/questor/cli.py` / `src/questorharness/bootstrap/hosts/app.py` |
| export | `src/questorharness/commands/families/workspace.py` | `src/questorharness/capabilities/memory/personalization/extractor.py` / `src/questorharness/bootstrap/cli/autopilot_commands.py` |
| fast | `src/questorharness/commands/families/model.py` | `src/questor/gateway/runtime.py` |
| feedback | `src/questorharness/commands/families/account.py` | `src/questorharness/capabilities/context/compact/limits.py` / `src/questorharness/capabilities/context/compact/prompts.py` |
| files | `src/questorharness/commands/families/workspace.py` | `src/questor/gateway/group_tool.py` / `src/questor/memory.py` |
| help | `src/questorharness/commands/families/session.py` | `src/questor/cli.py` / `src/questor/workspace.py` |
| hooks | `src/questorharness/commands/families/memory.py` | `src/questorharness/bootstrap/runtime.py` / `src/questorharness/capabilities/context/compact/__init__.py` |
| init | `src/questorharness/commands/families/workspace.py` | `src/questor/cli.py` / `src/questorharness/capabilities/memory/personalization/extractor.py` |
| issue | `src/questorharness/commands/families/project.py` | `src/questorharness/capabilities/context/coordinator.py` / `src/questorharness/bootstrap/cli/autopilot_commands.py` |
| keybindings | `src/questorharness/commands/families/appearance.py` | — |
| login | `src/questorharness/commands/families/account.py` | `src/questor/gateway/bridge.py` / `src/questorharness/bootstrap/runtime.py` |
| logout | `src/questorharness/commands/families/account.py` | `src/questorharness/bootstrap/cli/main.py` / `src/questorharness/bootstrap/cli/preview.py` |
| mcp | `src/questorharness/commands/families/plugin_management.py` | `src/questorharness/bootstrap/runtime.py` |
| memory | `src/questorharness/commands/families/memory.py` | `src/questor/cli.py` / `src/questor/gateway/router.py` |
| model | `src/questorharness/commands/families/model.py` | `src/questor/cli.py` / `src/questor/gateway/bridge.py` |
| onboarding | `src/questorharness/commands/families/account.py` | `src/questorharness/bootstrap/cli/preview.py` |
| output-style | `src/questorharness/commands/families/appearance.py` | `src/questorharness/bootstrap/cli/preview.py` |
| passes | `src/questorharness/commands/families/model.py` | — |
| permissions | `src/questorharness/commands/families/policy.py` | `src/questor/cli.py` |
| plan | `src/questorharness/commands/families/policy.py` | `src/questor/cli.py` |
| plugin | `src/questorharness/commands/families/plugin_management.py` | `src/questorharness/bootstrap/runtime.py` / `src/questorharness/capabilities/skills/loader.py` |
| pr_comments | `src/questorharness/commands/families/project.py` | `src/questorharness/bootstrap/cli/preview.py` / `src/questorharness/platform/paths.py` |
| privacy-settings | `src/questorharness/commands/families/diagnostics.py` | `src/questorharness/bootstrap/cli/preview.py` |
| provider | `src/questorharness/commands/families/model.py` | `src/questor/cli.py` / `src/questor/gateway/media.py` |
| rate-limit-options | `src/questorharness/commands/families/diagnostics.py` | `src/questorharness/bootstrap/cli/preview.py` |
| release-notes | `src/questorharness/commands/families/diagnostics.py` | `src/questorharness/bootstrap/cli/preview.py` |
| reload-plugins | `src/questorharness/commands/families/plugin_management.py` | `src/questorharness/bootstrap/cli/preview.py` |
| resume | `src/questorharness/commands/families/workspace.py` | `src/questor/cli.py` |
| review | `src/questorharness/commands/command_display.py` | `src/questorharness/capabilities/context/coordinator.py` / `src/questorharness/capabilities/memory/consolidate/prompt.py` |
| rewind | `src/questorharness/commands/families/workspace.py` | `src/questorharness/bootstrap/cli/preview.py` / `src/questorharness/commands/families/diagnostics.py` |
| session | `src/questorharness/commands/families/workspace.py` | `src/questor/cli.py` / `src/questor/gateway/bridge.py` |
| share | `src/questorharness/commands/families/workspace.py` | `src/questorharness/bootstrap/hosts/coordinator_drain.py` / `src/questorharness/capabilities/memory/consolidate/prompt.py` |
| ship | `src/questorharness/commands/families/agents.py` | `src/questorharness/bootstrap/cli/preview.py` |
| simplify | `src/questorharness/commands/command_display.py` | — |
| skill-creator | `src/questorharness/commands/command_display.py` | — |
| skills | `src/questorharness/commands/families/account.py` | `src/questor/workspace.py` / `src/questorharness/capabilities/context/compact/attachments.py` |
| stats | `src/questorharness/commands/families/session.py` | `src/questorharness/capabilities/tools/fs/file_edit_tool.py` / `src/questorharness/capabilities/tools/fs/file_write_tool.py` |
| status | `src/questorharness/commands/families/session.py` | `src/questor/cli.py` / `src/questor/gateway/bridge.py` |
| stop | `src/questorharness/commands/families/model.py` | `src/questor/cli.py` / `src/questor/gateway/bridge.py` |
| subagents | `src/questorharness/commands/families/agents.py` | `src/questorharness/capabilities/context/prompts/context.py` / `src/questorharness/capabilities/tools/agent/agent_tool.py` |
| summary | `src/questorharness/commands/families/session.py` | `src/questor/gateway/media.py` / `src/questor/gateway/runtime.py` |
| tag | `src/questorharness/commands/families/workspace.py` | `src/questorharness/capabilities/context/coordinator.py` / `src/questorharness/capabilities/memory/extract/__init__.py` |
| tasks | `src/questorharness/commands/families/agents.py` | `src/questorharness/bootstrap/hosts/app.py` |
| test | `src/questorharness/commands/command_display.py` | `src/questor/__main__.py` / `src/questor/gateway/bridge.py` |
| theme | `src/questorharness/commands/families/appearance.py` | `src/questor/runtime.py` |
| turns | `src/questorharness/commands/families/model.py` | `src/questor/cli.py` / `src/questor/gateway/runtime.py` |
| upgrade | `src/questorharness/commands/families/diagnostics.py` | `src/questorharness/bootstrap/cli/preview.py` |
| usage | `src/questorharness/commands/families/session.py` | `src/questor/gateway/runtime.py` / `src/questor/session_storage.py` |
| version | `src/questorharness/commands/families/session.py` | `src/questorharness/capabilities/context/prompts/environment.py` / `src/questorharness/capabilities/memory/personalization/extractor.py` |
| voice | `src/questorharness/commands/families/appearance.py` | `src/questorharness/bootstrap/cli/preview.py` |

## event

共 9 条。

| name | producer | consumers |
| --- | --- | --- |
| AssistantTextDelta | `src/questorharness/contracts/domain/events.py` | `src/questor/gateway/runtime.py` / `src/questor/runtime.py` |
| AssistantTurnComplete | `src/questorharness/contracts/domain/events.py` | `src/questor/gateway/runtime.py` / `src/questor/runtime.py` |
| CompactProgressEvent | `src/questorharness/contracts/domain/events.py` | `src/questor/gateway/runtime.py` / `src/questor/runtime.py` |
| ErrorEvent | `src/questorharness/contracts/domain/events.py` | `src/questor/gateway/runtime.py` / `src/questor/runtime.py` |
| InboundMessage | `src/questorharness/surfaces/channels/bus/events.py` | `src/questor/gateway/bridge.py` / `src/questor/gateway/router.py` |
| OutboundMessage | `src/questorharness/surfaces/channels/bus/events.py` | `src/questor/gateway/bridge.py` / `src/questor/gateway/gateway_process.py` |
| StatusEvent | `src/questorharness/contracts/domain/events.py` | `src/questor/gateway/runtime.py` / `src/questor/runtime.py` |
| ToolExecutionCompleted | `src/questorharness/contracts/domain/events.py` | `src/questor/gateway/media.py` / `src/questor/gateway/runtime.py` |
| ToolExecutionStarted | `src/questorharness/contracts/domain/events.py` | `src/questor/gateway/runtime.py` / `src/questorharness/api.py` |

## config-key

共 32 条。

| name | producer | consumers |
| --- | --- | --- |
| active_profile | `src/questorharness/config/settings_models.py` | `src/questor/gateway/runtime.py` / `src/questor/runtime.py` |
| allow_project_plugins | `src/questorharness/config/settings_models.py` | `src/questorharness/plugins/loader.py` |
| allow_project_skills | `src/questorharness/config/settings_models.py` | `src/questorharness/capabilities/skills/loader.py` |
| api_format | `src/questorharness/config/settings_models.py` | `src/questorharness/bootstrap/hosts/app.py` |
| api_key | `src/questorharness/config/settings_models.py` | `src/questorharness/bootstrap/hosts/app.py` |
| auto_compact_threshold_tokens | `src/questorharness/config/settings_models.py` | `src/questorharness/bootstrap/runtime.py` / `src/questorharness/capabilities/context/compact/__init__.py` |
| base_url | `src/questorharness/config/settings_models.py` | `src/questor/gateway/provider_commands.py` / `src/questorharness/bootstrap/hosts/app.py` |
| context_window_tokens | `src/questorharness/config/settings_models.py` | `src/questorharness/bootstrap/runtime.py` / `src/questorharness/capabilities/context/compact/__init__.py` |
| effort | `src/questorharness/config/settings_models.py` | `src/questorharness/bootstrap/hosts/app.py` |
| enabled_plugins | `src/questorharness/config/settings_models.py` | `src/questorharness/commands/families/plugin_management.py` / `src/questorharness/plugins/loader.py` |
| fast_mode | `src/questorharness/config/settings_models.py` | — |
| hooks | `src/questorharness/config/settings_models.py` | `src/questorharness/bootstrap/runtime.py` / `src/questorharness/capabilities/context/compact/__init__.py` |
| image_generation | `src/questorharness/config/settings_models.py` | `src/questor/gateway/media.py` / `src/questorharness/bootstrap/runtime.py` |
| max_tokens | `src/questorharness/config/settings_models.py` | `src/questorharness/bootstrap/runtime.py` / `src/questorharness/capabilities/context/compact/__init__.py` |
| max_turns | `src/questorharness/config/settings_models.py` | `src/questor/cli.py` / `src/questor/gateway/runtime.py` |
| mcp_servers | `src/questorharness/config/settings_models.py` | — |
| memory | `src/questorharness/config/settings_models.py` | `src/questor/cli.py` / `src/questor/gateway/router.py` |
| model | `src/questorharness/config/settings_models.py` | `src/questor/cli.py` / `src/questor/gateway/bridge.py` |
| output_style | `src/questorharness/config/settings_models.py` | — |
| passes | `src/questorharness/config/settings_models.py` | — |
| permission | `src/questorharness/config/settings_models.py` | — |
| profiles | `src/questorharness/config/settings_models.py` | `src/questor/gateway/provider_commands.py` / `src/questorharness/bootstrap/runtime.py` |
| project_skill_dirs | `src/questorharness/config/settings_models.py` | `src/questorharness/capabilities/skills/loader.py` |
| provider | `src/questorharness/config/settings_models.py` | `src/questor/cli.py` / `src/questor/gateway/media.py` |
| sandbox | `src/questorharness/config/settings_models.py` | `src/questorharness/bootstrap/runtime.py` / `src/questorharness/capabilities/ports.py` |
| system_prompt | `src/questorharness/config/settings_models.py` | `src/questor/gateway/runtime.py` / `src/questor/runtime.py` |
| theme | `src/questorharness/config/settings_models.py` | `src/questor/runtime.py` |
| timeout | `src/questorharness/config/settings_models.py` | `src/questor/gateway/bridge.py` |
| verbose | `src/questorharness/config/settings_models.py` | `src/questorharness/bootstrap/cli/main.py` / `src/questorharness/runtime/bridge/models.py` |
| vision | `src/questorharness/config/settings_models.py` | `src/questor/gateway/runtime.py` / `src/questorharness/bootstrap/runtime.py` |
| voice_mode | `src/questorharness/config/settings_models.py` | `src/questorharness/bootstrap/runtime.py` / `src/questorharness/commands/families/appearance.py` |
| web | `src/questorharness/config/settings_models.py` | `src/questorharness/capabilities/tools/registry.py` / `src/questorharness/capabilities/tools/web/web_fetch_tool.py` |

## env

共 53 条。

| name | producer | consumers |
| --- | --- | --- |
| QUESTORHARNESS_AGENT_TEAMS | `src/questorharness/runtime/swarm/spawn_utils.py` | — |
| QUESTORHARNESS_ANTHROPIC_API_KEY | `src/questorharness/config/settings_models.py` | `src/questorharness/runtime/swarm/spawn_utils.py` |
| QUESTORHARNESS_API_FORMAT | `src/questorharness/capabilities/memory/consolidate/dream.py` | `src/questorharness/config/settings_loader.py` / `src/questorharness/runtime/swarm/spawn_utils.py` |
| QUESTORHARNESS_API_KEY | `src/questorharness/capabilities/memory/consolidate/dream.py` | — |
| QUESTORHARNESS_AUTODREAM_CHILD | `src/questorharness/capabilities/memory/consolidate/dream.py` | — |
| QUESTORHARNESS_AUTODREAM_MEMORY_DIR | `src/questorharness/capabilities/memory/consolidate/dream.py` | — |
| QUESTORHARNESS_AUTO_COMPACT_THRESHOLD_TOKENS | `src/questorharness/config/settings_loader.py` | — |
| QUESTORHARNESS_BASE_URL | `src/questorharness/capabilities/memory/consolidate/dream.py` | `src/questorharness/config/settings_loader.py` / `src/questorharness/runtime/swarm/spawn_utils.py` |
| QUESTORHARNESS_CHANNEL_MEDIA_DIR | `src/questor/gateway/gateway_process.py` | `src/questorharness/surfaces/channels/impl/base_channel.py` |
| QUESTORHARNESS_CONFIG_DIR | `src/questorharness/capabilities/memory/consolidate/dream.py` | `src/questorharness/platform/paths.py` / `src/questorharness/runtime/swarm/spawn_utils.py` |
| QUESTORHARNESS_CONTEXT_WINDOW_TOKENS | `src/questorharness/config/settings_loader.py` | — |
| QUESTORHARNESS_DASHSCOPE_API_KEY | `src/questorharness/config/settings_models.py` | `src/questorharness/runtime/swarm/spawn_utils.py` |
| QUESTORHARNESS_DATA_DIR | `src/questorharness/platform/paths.py` | `src/questorharness/runtime/swarm/spawn_utils.py` |
| QUESTORHARNESS_GEMINI_API_KEY | `src/questorharness/config/settings_models.py` | `src/questorharness/runtime/swarm/spawn_utils.py` |
| QUESTORHARNESS_HOOK_EVENT | `src/questorharness/runtime/hooks/executor.py` | — |
| QUESTORHARNESS_HOOK_PAYLOAD | `src/questorharness/runtime/hooks/executor.py` | — |
| QUESTORHARNESS_IMAGE_GENERATION_API_KEY | `src/questorharness/config/settings_models.py` | `src/questorharness/capabilities/tools/media/image_generation_tool.py` |
| QUESTORHARNESS_IMAGE_GENERATION_BASE_URL | `src/questorharness/config/settings_models.py` | — |
| QUESTORHARNESS_IMAGE_GENERATION_CODEX_BASE_URL | `src/questorharness/config/settings_models.py` | — |
| QUESTORHARNESS_IMAGE_GENERATION_CODEX_MODEL | `src/questorharness/config/settings_models.py` | — |
| QUESTORHARNESS_IMAGE_GENERATION_MODEL | `src/questorharness/config/settings_models.py` | — |
| QUESTORHARNESS_IMAGE_GENERATION_PROVIDER | `src/questorharness/config/settings_models.py` | — |
| QUESTORHARNESS_IMAGE_TOKEN_ESTIMATE | `src/questorharness/capabilities/context/compact/tokens.py` | — |
| QUESTORHARNESS_LOGS_DIR | `src/questorharness/platform/paths.py` | `src/questorharness/runtime/swarm/spawn_utils.py` |
| QUESTORHARNESS_LOG_LEVEL | `src/questorharness/bootstrap/cli/main.py` | — |
| QUESTORHARNESS_MAX_TOKENS | `src/questorharness/config/settings_loader.py` | — |
| QUESTORHARNESS_MAX_TURNS | `src/questorharness/config/settings_loader.py` | — |
| QUESTORHARNESS_MICROCOMPACT_TOOL_RESULT_CHARS | `src/questorharness/contracts/tool_outputs.py` | — |
| QUESTORHARNESS_MINIMAX_API_KEY | `src/questorharness/config/settings_models.py` | `src/questorharness/runtime/swarm/spawn_utils.py` |
| QUESTORHARNESS_MODEL | `src/questorharness/capabilities/memory/consolidate/dream.py` | `src/questorharness/config/settings_loader.py` / `src/questorharness/runtime/swarm/spawn_utils.py` |
| QUESTORHARNESS_MODELSCOPE_API_KEY | `src/questorharness/config/settings_models.py` | `src/questorharness/runtime/swarm/spawn_utils.py` |
| QUESTORHARNESS_MOONSHOT_API_KEY | `src/questorharness/config/settings_models.py` | `src/questorharness/runtime/swarm/spawn_utils.py` |
| QUESTORHARNESS_NVIDIA_API_KEY | `src/questorharness/config/settings_models.py` | `src/questorharness/runtime/swarm/spawn_utils.py` |
| QUESTORHARNESS_OPENAI_API_KEY | `src/questorharness/config/settings_models.py` | `src/questorharness/runtime/swarm/spawn_utils.py` |
| QUESTORHARNESS_PROFILE | `src/questorharness/capabilities/memory/consolidate/dream.py` | `src/questorharness/config/settings_loader.py` / `src/questorharness/config/settings_models.py` |
| QUESTORHARNESS_PROVIDER | `src/questorharness/capabilities/memory/consolidate/dream.py` | `src/questorharness/config/settings_loader.py` / `src/questorharness/runtime/swarm/spawn_utils.py` |
| QUESTORHARNESS_REQUIRE_EMPTY_REASONING_CONTENT | `src/questorharness/providers/llm/openai_client.py` | — |
| QUESTORHARNESS_SANDBOX_BACKEND | `src/questorharness/config/settings_loader.py` | — |
| QUESTORHARNESS_SANDBOX_DOCKER_IMAGE | `src/questorharness/config/settings_loader.py` | — |
| QUESTORHARNESS_SANDBOX_ENABLED | `src/questorharness/config/settings_loader.py` | — |
| QUESTORHARNESS_SANDBOX_FAIL_IF_UNAVAILABLE | `src/questorharness/config/settings_loader.py` | — |
| QUESTORHARNESS_TEAMMATE_COMMAND | `src/questorharness/runtime/swarm/spawn_utils.py` | — |
| QUESTORHARNESS_TEAMMATE_MODE | `src/questorharness/runtime/swarm/registry.py` | — |
| QUESTORHARNESS_TIMEOUT | `src/questorharness/config/settings_loader.py` | — |
| QUESTORHARNESS_TOOL_OUTPUT_INLINE_CHARS | `src/questorharness/contracts/tool_outputs.py` | — |
| QUESTORHARNESS_TOOL_OUTPUT_PREVIEW_CHARS | `src/questorharness/contracts/tool_outputs.py` | — |
| QUESTORHARNESS_VISION_API_KEY | `src/questorharness/config/settings_models.py` | `src/questorharness/capabilities/tools/media/image_to_text_tool.py` |
| QUESTORHARNESS_VISION_BASE_URL | `src/questorharness/config/settings_models.py` | — |
| QUESTORHARNESS_VISION_MODEL | `src/questorharness/config/settings_models.py` | `src/questorharness/capabilities/tools/media/image_to_text_tool.py` |
| QUESTORHARNESS_WEB_PROXY | `src/questorharness/config/settings_loader.py` | — |
| QUESTORHARNESS_WEB_RESOLUTION_MODE | `src/questorharness/config/settings_loader.py` | — |
| QUESTORHARNESS_WEB_SEARCH_URL | `src/questorharness/capabilities/tools/web/web_search_tool.py` | — |
| QUESTORHARNESS_WEB_SYNTHETIC_DNS_CIDRS | `src/questorharness/config/settings_loader.py` | — |

## entry-point

共 5 条。

| name | producer | consumers |
| --- | --- | --- |
| oh | `pyproject.toml` | `src/questor/gateway/bridge.py` / `src/questorharness/bootstrap/runtime.py` |
| openh | `pyproject.toml` | — |
| questor | `pyproject.toml` | `src/questor/__init__.py` / `src/questor/__main__.py` |
| questorharness | `pyproject.toml` | `src/questor/cli.py` / `src/questor/gateway/bridge.py` |
| questorharness.notification_handlers:questor-feishu | `pyproject.toml` | — |

## skill-id

共 8 条。

| name | producer | consumers |
| --- | --- | --- |
| commit | `src/questorharness/capabilities/skills/bundled/__init__.py` | `src/questorharness/capabilities/context/coordinator.py` / `src/questorharness/bootstrap/cli/preview.py` |
| debug | `src/questorharness/capabilities/skills/bundled/__init__.py` | `src/questorharness/capabilities/schedule/cron_scheduler.py` |
| diagnose | `src/questorharness/capabilities/skills/bundled/__init__.py` | `src/questorharness/capabilities/context/prompts/system_prompt.py` |
| plan | `src/questorharness/capabilities/skills/bundled/__init__.py` | `src/questor/cli.py` |
| review | `src/questorharness/capabilities/skills/bundled/__init__.py` | `src/questorharness/capabilities/context/coordinator.py` / `src/questorharness/capabilities/memory/consolidate/prompt.py` |
| simplify | `src/questorharness/capabilities/skills/bundled/__init__.py` | — |
| skill-creator | `src/questorharness/capabilities/skills/bundled/__init__.py` | — |
| test | `src/questorharness/capabilities/skills/bundled/__init__.py` | `src/questor/__main__.py` / `src/questor/gateway/bridge.py` |
