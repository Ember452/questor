# 环境变量

配置的解析顺序：**内置默认值 → `settings.json` → 环境变量 → 命令行参数**。
环境变量永远覆盖配置文件；命令行参数覆盖一切。

`QUESTORHARNESS_*` 前缀的变量一律生效。非前缀变量（`ANTHROPIC_*`、`OPENAI_*`）只在
当前 profile **没有显式配置**对应字段时才生效——这是为了不悄悄覆盖用户写进配置的意图。
实现在 `src/questorharness/config/settings_loader.py`。

## 路径

| 变量 | 作用 | 默认 |
| --- | --- | --- |
| `QUESTORHARNESS_CONFIG_DIR` | 配置目录 | `~/.questorharness/` |
| `QUESTORHARNESS_DATA_DIR` | 数据目录（会话、事件、缓存） | `<配置目录>/data/` |
| `QUESTORHARNESS_LOGS_DIR` | 日志目录 | `<配置目录>/logs/` |
| `QUESTORHARNESS_CHANNEL_MEDIA_DIR` | 渠道（飞书 / QQ）媒体落盘目录 | 由应用启动时注入 |
| `QUESTOR_WORKSPACE` | 产品 workspace 根 | `~/.questor/agent` |
| `QUESTOR_WEB_DIST` | 覆盖回环宿主提供的前端构建产物目录 | 内置目录 |
| `QUESTOR_PROFILE_ROOT` | 行式客户端的 profile 根目录 | 内置目录 |

## 模型与请求

| 变量 | 对应字段 | 说明 |
| --- | --- | --- |
| `QUESTORHARNESS_MODEL` | `model` | 模型名，始终覆盖 |
| `QUESTORHARNESS_BASE_URL` | `base_url` | API 基址，始终覆盖 |
| `QUESTORHARNESS_MAX_TOKENS` | `max_tokens` | 单次请求输出上限 |
| `QUESTORHARNESS_TIMEOUT` | `timeout` | 请求超时（秒，浮点） |
| `QUESTORHARNESS_MAX_TURNS` | `max_turns` | 最大 agentic 回合数 |
| `QUESTORHARNESS_PROVIDER` | `provider` | provider 名 |
| `QUESTORHARNESS_API_FORMAT` | `api_format` | `anthropic` / `openai` / `copilot` |
| `QUESTORHARNESS_PROFILE` | `active_profile` | 选择活动 profile |

非前缀兼容变量（仅当 profile 未显式配置时生效）：

| 变量 | 对应字段 |
| --- | --- |
| `ANTHROPIC_MODEL` / `OPENAI_MODEL` | `model` |
| `ANTHROPIC_BASE_URL` / `OPENAI_BASE_URL` | `base_url` |

## 凭据

凭据按当前 profile 的 `auth_source` 解析，常用的有：

`QUESTORHARNESS_API_KEY`、`QUESTORHARNESS_ANTHROPIC_API_KEY`、`QUESTORHARNESS_OPENAI_API_KEY`、
`QUESTORHARNESS_GEMINI_API_KEY`、`QUESTORHARNESS_DASHSCOPE_API_KEY`、`QUESTORHARNESS_MOONSHOT_API_KEY`、
`QUESTORHARNESS_MINIMAX_API_KEY`、`QUESTORHARNESS_NVIDIA_API_KEY`、`QUESTORHARNESS_MODELSCOPE_API_KEY`。

命令行 `-k/--api-key` 优先级最高。没有任何可用凭据时，引擎回落到 echo 演示 provider。

## 上下文与压缩

| 变量 | 对应字段 | 说明 |
| --- | --- | --- |
| `QUESTORHARNESS_CONTEXT_WINDOW_TOKENS` | `context_window_tokens` | 模型上下文窗口；用于估算压缩阈值与输出上限 |
| `QUESTORHARNESS_AUTO_COMPACT_THRESHOLD_TOKENS` | `auto_compact_threshold_tokens` | 自动压缩触发阈值 |

## 沙箱

| 变量 | 对应字段 |
| --- | --- |
| `QUESTORHARNESS_SANDBOX_ENABLED` | `sandbox.enabled` |
| `QUESTORHARNESS_SANDBOX_FAIL_IF_UNAVAILABLE` | `sandbox.fail_if_unavailable` |
| `QUESTORHARNESS_SANDBOX_BACKEND` | `sandbox.backend`（`srt` / `docker`） |
| `QUESTORHARNESS_SANDBOX_DOCKER_IMAGE` | `sandbox.docker.image` |

## 网络工具

| 变量 | 对应字段 |
| --- | --- |
| `QUESTORHARNESS_WEB_PROXY` | `web.proxy` |
| `QUESTORHARNESS_WEB_RESOLUTION_MODE` | `web.resolution_mode` |
| `QUESTORHARNESS_WEB_SYNTHETIC_DNS_CIDRS` | `web.synthetic_dns_cidrs`（逗号分隔） |
| `QUESTORHARNESS_WEB_SEARCH_URL` | 内置 web 搜索端点 |

## 日志

| 变量 | 说明 |
| --- | --- |
| `QUESTORHARNESS_LOG_LEVEL` | 日志级别（`DEBUG` / `INFO` / `WARNING`…），默认 `WARNING` |
| `QUESTORHARNESS_LOGS_DIR` | 日志文件目录 |

## 视觉与图像生成

`QUESTORHARNESS_VISION_MODEL`、`QUESTORHARNESS_VISION_API_KEY`、`QUESTORHARNESS_VISION_BASE_URL`、
以及 `QUESTORHARNESS_IMAGE_GENERATION_*` 系列，对应 `vision` 与 `image_generation` 两个配置块。

## 内部变量（非稳定接口）

以下变量由引擎内部或测试使用，**不属于对外契约**，随时可能改名：
`QUESTORHARNESS_HOOK_EVENT`、`QUESTORHARNESS_HOOK_PAYLOAD`、`QUESTORHARNESS_TEAMMATE_*`、
`QUESTORHARNESS_AGENT_TEAMS`、`QUESTORHARNESS_AUTODREAM_*`、`QUESTORHARNESS_TOOL_OUTPUT_*`、
`QUESTORHARNESS_MICROCOMPACT_TOOL_RESULT_CHARS`、`QUESTORHARNESS_IMAGE_TOKEN_ESTIMATE`、
`QUESTORHARNESS_GREP_TIMEOUT__`、`QUESTORHARNESS_REQUIRE_EMPTY_REASONING_CONTENT`。
