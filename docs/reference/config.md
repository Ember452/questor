# 配置参考

配置文件：`~/.questorharness/settings.json`（`QUESTORHARNESS_CONFIG_DIR` 可改目录）。
默认路径由 `src/questorharness/platform/paths.py` 解析，字段模型在
`src/questorharness/config/settings_models.py`。

解析顺序：**默认值 → settings.json → 环境变量 → 命令行参数**。下文"默认"列取自模型定义。

## 顶层字段

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `api_key` | `""` | 直接写密钥；更推荐用环境变量或凭据存储 |
| `model` | `claude-sonnet-4-6` | 默认模型 |
| `max_tokens` | `16384` | 单次响应输出上限（会被上下文窗口安全上限钳制） |
| `base_url` | `null` | API 基址；`null` 表示用 provider 默认 |
| `timeout` | `30.0` | 请求超时（秒） |
| `context_window_tokens` | `null` | 模型上下文窗口 |
| `auto_compact_threshold_tokens` | `null` | 自动压缩阈值 |
| `api_format` | `anthropic` | `anthropic` / `openai` / `copilot` |
| `provider` | `""` | provider 名 |
| `active_profile` | `claude-api` | 当前生效的 profile |
| `profiles` | 内置 profile 集 | 见下节 |
| `max_turns` | `200` | 最大 agentic 回合数 |
| `system_prompt` | `null` | 覆盖默认系统提示词 |
| `theme` | `default` | TUI 主题 |
| `output_style` | `default` | 输出风格 |
| `effort` | `medium` | 模型强度档 |
| `passes` | `1` | 单轮重复通过的次数 |
| `verbose` | `false` | 详细输出 |
| `fast_mode` | `false` | 快速模式 |
| `voice_mode` | `false` | 语音模式开关（当前无语音能力，仅为字段保留） |
| `allow_project_plugins` | `false` | 是否允许从项目目录加载插件 |
| `allow_project_skills` | `true` | 是否允许从项目目录加载技能 |
| `project_skill_dirs` | 内置列表 | 项目技能搜索目录 |
| `enabled_plugins` | `{}` | 插件开关表 |
| `mcp_servers` | `{}` | MCP 服务器配置，见 [MCP 集成](../integrations/mcp.md) |

## `permission`

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `mode` | `default` | `default` / `plan` / `full_auto` |
| `allowed_tools` | `[]` | 工具白名单（最高优先级的放行） |
| `denied_tools` | `[]` | 工具黑名单 |
| `path_rules` | `[]` | 路径 glob 规则，元素为 `{"pattern": "...", "allow": true\|false}` |
| `denied_commands` | `[]` | 命令 deny 模式（fnmatch 语法） |

内置的敏感路径保护（SSH、云凭据、GPG、Kubernetes、本仓凭据文件等）**不受上述字段影响**，
任何模式下都拒绝。判定顺序见 [工具与权限](../internals/03-tools-and-permissions.md)。

## `memory`

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `enabled` | `true` | 记忆总开关 |
| `max_files` | `5` | 注入上下文的记忆文件上限 |
| `max_entrypoint_lines` | `200` | 入口文件行数上限 |
| `max_entrypoint_bytes` | `25000` | 入口文件字节上限 |
| `context_window_tokens` / `auto_compact_threshold_tokens` | `null` | 覆盖记忆子系统的窗口设置 |
| `auto_extract_enabled` | `false` | 自动抽取记忆条目 |
| `auto_extract_max_records` | `3` | 每次抽取的条数上限 |
| `session_memory_enabled` | `true` | 会话级记忆 |
| `auto_dream_enabled` | `false` | 自动蒸馏（Deep Dream） |
| `auto_dream_min_hours` | `24.0` | 蒸馏最小间隔（小时） |
| `auto_dream_min_sessions` | `5` | 触发蒸馏的最小会话数 |

## `sandbox`

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `enabled` | `false` | 沙箱总开关 |
| `backend` | `srt` | `srt` 或 `docker` |
| `fail_if_unavailable` | `false` | 沙箱不可用时是 fail-closed 还是降级运行 |
| `enabled_platforms` | `[]` | 仅在指定平台启用 |
| `network.allowed_domains` / `denied_domains` | `[]` | 网络域名黑白名单 |
| `filesystem.allow_read` / `deny_read` | `[]` | 读路径规则 |
| `filesystem.allow_write` | `["."]` | 写路径规则，默认只允许当前目录 |
| `filesystem.deny_write` | `[]` | 写路径拒绝规则 |
| `docker.image` | `questorharness-sandbox:latest` | Docker 沙箱镜像 |
| `docker.auto_build_image` | `true` | 镜像缺失时自动构建 |
| `docker.cpu_limit` / `memory_limit` | `0.0` / `""` | 资源限制，空表示不限制 |
| `docker.extra_mounts` / `extra_env` | `[]` / `{}` | 额外挂载与环境变量 |

## `web` 与模型扩展

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `web.proxy` | `null` | 网络工具代理 |
| `web.resolution_mode` | `auto` | 域名解析模式 |
| `web.synthetic_dns_cidrs` | `[]` | 合成 DNS 的 CIDR 段 |
| `vision.model` / `vision.api_key` / `vision.base_url` | `""` | 图像理解模型配置 |
| `image_generation.provider` | `auto` | 图像生成后端 |
| `image_generation.model` | `gpt-image-2` | 图像生成模型 |

## `profiles`

`profiles` 是"供应商档位"表，键为 profile 名，值为：

| 字段 | 说明 |
| --- | --- |
| `label` | 展示名 |
| `provider` | provider 标识 |
| `api_format` | 该档位使用的协议 |
| `auth_source` | 凭据来源（决定读哪个环境变量或凭据槽） |
| `default_model` | 该档位的默认模型 |
| `base_url` | 基址覆盖 |
| `last_model` | 上次使用的模型；非空时 `ANTHROPIC_MODEL` 之类不再覆盖 |
| `credential_slot` | 凭据存储槽位 |
| `allowed_models` | 该档位允许的模型列表 |
| `context_window_tokens` / `auto_compact_threshold_tokens` | 档位级窗口设置 |

改这份配置的推荐方式是 `questorharness provider` 与 `questorharness config` 子命令，
手改 JSON 容易与 profile 的"扁平字段"同步逻辑冲突。
