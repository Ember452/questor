# 参考手册

按"查一个具体值"组织的文档：命令、参数、环境变量、配置字段。

| 我想查 | 看这篇 |
| --- | --- |
| 有哪些命令、参数分别属于哪个入口 | [CLI 参考](cli.md) |
| 环境变量怎么覆盖配置、优先级如何 | [环境变量](env.md) |
| `settings.json` 每个字段的含义与默认值 | [配置参考](config.md) |

## 两个入口，别混用

| 入口 | 是什么 | 典型用途 |
| --- | --- | --- |
| `python -m questor`（`questor`） | 产品应用：workspace、网关、记忆、行式 REPL | 日常个人使用 |
| `python -m questorharness`（`questorharness` / `oh` / `openh`） | 引擎：全屏 TUI、权限控制、沙箱、cron、autopilot | 开发、调试、自动化 |

参数不通用：`--permission-mode`、`--plain`、`--dry-run`、`--mcp-config` 等只在引擎入口上。
