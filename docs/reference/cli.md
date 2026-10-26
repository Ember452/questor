# CLI 参考

两个入口是两套命令。本文按入口分节，参数与实现同步；`--help` 是最终事实。

## 入口一览

| 命令 | 装的脚本名 | 默认行为 |
| --- | --- | --- |
| `python -m questor` | `questor` | 启动产品行式 REPL（questor workspace + 产品系统提示词） |
| `python -m questorharness` | `questorharness`、`oh`、`openh` | 启动引擎全屏 TUI；非 TTY 或 `--plain` 时降级为行式 REPL |

## 产品入口 `questor`

### 全局参数

| 参数 | 说明 |
| --- | --- |
| `-p, --print <prompt>` | 单次执行后退出 |
| `--model <name>` | 本次会话的模型覆盖 |
| `--profile <name>` | 指定 provider profile |
| `--workspace <path>` | 产品 workspace 路径，默认 `~/.questor/agent` |
| `--max-turns <int>` | 覆盖最大回合数 |
| `--cwd <path>` | 工作目录，默认当前目录 |
| `--resume <session-id>` | 恢复指定会话 |
| `--continue` | 继续本目录最近一次会话 |

### 子命令

| 命令 | 作用 |
| --- | --- |
| `questor init` | 初始化产品 workspace |
| `questor config` | 配置 provider profile 与网关渠道 |
| `questor doctor` | 检查 workspace 与 provider 可用性 |
| `questor memory` | 管理个人记忆（`add` / `list` / `remove`） |
| `questor soul` | 查看或编辑 `soul.md` |
| `questor user` | 查看或编辑 `user.md` |
| `questor gateway` | 运行产品网关（飞书 / QQ 等渠道） |

## 引擎入口 `questorharness`

### 会话

| 参数 | 说明 |
| --- | --- |
| `-c, --continue` | 继续当前目录最近一次会话 |
| `-r, --resume <id>` | 按会话 ID 恢复；不给 ID 时打开选择器 |
| `-n, --name <name>` | 给本次会话设置显示名 |

### 模型与强度

| 参数 | 说明 |
| --- | --- |
| `-m, --model <name>` | 模型别名（如 `sonnet`、`opus`）或完整模型 ID |
| `--effort <level>` | `low` / `medium` / `high` / `xhigh` / `max` |
| `--max-turns <int>` | 最大 agentic 回合数；`--print` 下默认强制 |
| `--verbose` | 覆盖配置里的 verbose 开关 |

### 输出

| 参数 | 说明 |
| --- | --- |
| `-p, --print <prompt>` | 打印响应后退出 |
| `--output-format <fmt>` | `text`（默认）/ `json` / `stream-json`，需配合 `--print` |
| `--dry-run` | 只打印解析后的配置、技能、命令、工具，不调模型、不执行工具 |

### 权限

| 参数 | 说明 |
| --- | --- |
| `--permission-mode <mode>` | `default` / `plan` / `full_auto` |
| `--allowed-tools <list>` | 逗号或空格分隔的工具白名单 |
| `--disallowed-tools <list>` | 逗号或空格分隔的工具黑名单 |
| `--dangerously-skip-permissions` | 跳过全部权限检查，**仅限隔离沙箱** |

### 系统与上下文

| 参数 | 说明 |
| --- | --- |
| `-s, --system-prompt <text>` | 覆盖默认系统提示词 |
| `--append-system-prompt <text>` | 在默认系统提示词后追加 |
| `--settings <path\|json>` | 指定 JSON 配置文件路径或内联 JSON |
| `--base-url <url>` | Anthropic 兼容 API 基址 |
| `-k, --api-key <key>` | API key，覆盖配置与环境变量 |
| `--api-format <fmt>` | `anthropic`（默认）/ `openai` / `copilot` |
| `--bare` | 最小化模式：跳过 hooks、插件、MCP 与自动发现 |
| `--plain` | 强制行式 REPL，不启用全屏 TUI |
| `--theme <name>` | TUI 主题 |

### 高级

| 参数 | 说明 |
| --- | --- |
| `-d, --debug` | 开启调试日志 |
| `--mcp-config <path\|json>` | 加载 MCP 服务器配置，可多次指定 |
| `-v, --version` | 打印版本 |

`--studio-host` 是桌面壳专用的回环宿主开关（不在常规帮助里展示），由 Electron 壳
自动传入，不要手工调用。

### 子命令

| 命令 | 作用 |
| --- | --- |
| `questorharness setup` | 统一初始化：选工作流、认证、设模型 |
| `questorharness auth` | 管理认证 |
| `questorharness provider` | 管理 provider profile |
| `questorharness config` | 查看或更新设置 |
| `questorharness mcp` | 管理 MCP 服务器（`list` / `add` / `remove`） |
| `questorharness plugin` | 管理插件 |
| `questorharness cron` | 管理定时任务 |
| `questorharness autopilot` | 管理仓库 autopilot |

MCP 的用法见 [MCP 集成](../integrations/mcp.md)。
