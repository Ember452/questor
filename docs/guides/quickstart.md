# 快速开始

目标：从一个空环境走到"第一次成功对话"，并知道会话、权限、配置分别在哪。

前置：已完成 [安装](install.md)，终端里能执行 `uv run python -m questor --help`。

## 1. 初始化工作区

```powershell
uv run python -m questor init
```

会在 `~/.questor/agent` 建立产品 workspace。要换位置用 `--workspace <path>`。

## 2. 配置模型

```powershell
uv run python -m questor config
```

交互式写入 provider profile 与凭据（保存在 `~/.questorharness/settings.json`）。
非交互场景可以直接用环境变量，优先级高于配置文件：

```powershell
$env:QUESTORHARNESS_MODEL = "claude-sonnet-4-6"
$env:QUESTORHARNESS_API_KEY = "sk-..."
```

`QUESTORHARNESS_*` 始终覆盖配置；`ANTHROPIC_*` / `OPENAI_*` 只在 profile 没有显式配置
对应字段时才生效。完整规则见 [环境变量](../reference/env.md)。

**没有凭据也能跑**：引擎会回落到 echo 演示 provider，用于验证链路是否通。

## 3. 自检

```powershell
uv run python -m questor doctor
```

## 4. 第一次对话

两个入口不是同一个程序，别混用：

| 入口 | 交互形态 | 语义 |
| --- | --- | --- |
| `python -m questor` | 行式 REPL | 产品语义：`~/.questor/agent` workspace + 产品系统提示词 |
| `python -m questorharness` | 全屏 TUI（非 TTY 自动降级行式） | 引擎语义：通用 coding harness |

```powershell
uv run python -m questor           # 行式 REPL
uv run python -m questorharness    # 全屏 TUI
```

单次提问后退出：

```powershell
uv run python -m questor -p "用三句话解释这个仓库的分层"
```

在管道、重定向或 CI 里运行时，引擎检测到 stdin/stdout 不是终端，会自动降级为行式
REPL；要强制行式模式加 `--plain`（仅引擎入口有该参数）。

## 5. 会话

| 我想 | 命令 |
| --- | --- |
| 继续最近一次会话 | `uv run python -m questor --continue` |
| 恢复指定会话 | `uv run python -m questor --resume <session-id>` |
| 指定工作目录 | `uv run python -m questor --cwd <path>` |
| 限制回合数 | `uv run python -m questor --max-turns 10` |

会话与事件日志存放在 `~/.questorharness/data/`，默认不写进当前仓库。

## 6. 权限

三种模式，默认 `default`（权限参数在**引擎**入口上，产品 CLI 不暴露）：

| 模式 | 行为 |
| --- | --- |
| `default` | 只读工具直接放行；改文件、执行命令需要你确认 |
| `plan` | 只读；所有变更型工具被拒绝，用于先出方案 |
| `full_auto` | 全部放行，仅在沙箱/一次性环境里使用 |

```powershell
uv run python -m questorharness --permission-mode plan
uv run python -m questorharness --allowed-tools read_file,grep
uv run python -m questorharness --disallowed-tools bash
```

无论哪种模式，内置敏感路径（`~/.ssh/`、`~/.aws/credentials`、`~/.questorharness/credentials.json` 等）
**一律拒绝**，不可被配置覆盖。判定顺序见 [工具与权限](../internals/03-tools-and-permissions.md)。

## 7. 想确认"引擎实际会用什么配置"

```powershell
uv run python -m questorharness --dry-run
```

它会打印解析后的运行时配置、技能、命令与工具列表，但不调用模型、不执行工具。

## 下一步

- 全部命令与参数：[CLI 参考](../reference/cli.md)
- 配置项含义：[配置参考](../reference/config.md)
- 一次 turn 到底发生了什么：[Turn 生命周期](../internals/01-turn-lifecycle.md)
- 出问题：[故障排查](troubleshooting.md)
