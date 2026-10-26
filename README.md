# Questor

> **本地优先的 Agent Harness + 桌面通用个人 Agent。**

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](./LICENSE)
![Python](https://img.shields.io/badge/Python-3.13-blue)
![Status](https://img.shields.io/badge/status-alpha-orange)

**状态：开发中（alpha）**。核心能力栈（分层 / 事件协议 / 工具与权限 / 断点续传 / 记忆 / Skills + MCP / 桌面壳）已落地并有测试与结构守卫覆盖；产品形态仍在演进，CLI 参数与内部契约可能在 minor 版本之间变化。

## 这是什么

Questor 分成两层：**引擎**负责通用的 Agent 运行时，**应用**负责产品组合与个人场景。换算法不动内核，换界面不动引擎。

| 层 | 职责 | 位置 |
| --- | --- | --- |
| Harness（引擎） | turn 循环、唯一可信状态、事件协议、工具路由、权限与沙箱、持久化与断点续传 | `src/questorharness` |
| Agent 应用 | 产品组合根：workspace、HTTP 网关、群策略、个人记忆 | `src/questor` |

三个宿主共享同一套协议：**终端全屏 TUI**（引擎 `questorharness`，默认）、**行式 REPL**（产品 `questor`，以及管道 / CI 场景）、**桌面应用**（Electron 壳 + `apps/web` 渲染层）。另有 OpenAI 兼容的本地 API 通道，供外部客户端接入。

## 亮点

- **分层解耦**：`contracts → platform → config → providers/execution → runtime → engine → capabilities → commands → surfaces → bootstrap` 单向依赖，由 `uv run lint-imports` 机械执行。
- **事件溯源**：引擎只产出事件，`Command` 才改状态；会话可断点续传、可恢复上下文压缩。
- **工具 + 权限**：工具、Skills、MCP 走同一套判定——内置敏感凭据路径永远拒绝，其余按 `default / plan / full_auto` 三态与路径白名单裁决。
- **上下文管理**：超过阈值先做低成本的微压缩（清理旧工具结果），不够再走 LLM 摘要；提示词超长时自动重压重试。
- **多供应商**：经 LiteLLM / OpenAI 兼容协议接入，支持 profile 切换与 BYOM；无凭据时回落到 echo 演示 provider，链路可先跑通。
- **可维护**：文档、目录结构、依赖方向、命名空间都有生成物和守卫，文档死链会让 CI 变红。

## 安装

### 从源码（推荐）

当前被持续验证的安装路径。需要 Python 3.13 与 [uv](https://docs.astral.sh/uv/)：

```powershell
git clone https://github.com/Ember452/questor.git
cd questor
uv sync
uv run python -m questor --help
```

### 一键脚本

仓库自带 `scripts/install.ps1`（Windows）与 `scripts/install.sh`（macOS / Linux），脚本从仓库 `main` 分支拉取，因此需要仓库可公开访问：

```powershell
iex (Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/Ember452/questor/main/scripts/install.ps1')
```

```bash
curl -fsSL https://raw.githubusercontent.com/Ember452/questor/main/scripts/install.sh | sh
```

桌面版需要额外构建前端与 Electron 壳，见 [桌面版指南](docs/guides/desktop.md)。

## 第一次运行

```powershell
uv run python -m questor init      # 初始化工作区
uv run python -m questor config    # 配置 provider profile 与凭据
uv run python -m questor doctor    # 自检工作区与凭据
uv run python -m questor           # 行式 REPL（产品语义：workspace + 产品系统提示词）
uv run python -m questor -p "总结这个仓库的结构"   # 单次提问后退出
uv run python -m questorharness    # 全屏 TUI（引擎语义；非 TTY 自动降级行式 REPL）
```

先跑通链路再接真模型：没配凭据时引擎会回落到 echo 演示 provider。配置写在 `~/.questorharness/settings.json`（可用 `QUESTORHARNESS_CONFIG_DIR` 改位置），产品 workspace 默认 `~/.questor/agent`。

## 文档

| 我想… | 看这篇 |
| --- | --- |
| 先跑起来 | [快速开始](docs/guides/quickstart.md) |
| 装桌面版 | [桌面版指南](docs/guides/desktop.md) |
| 查命令与参数 | [CLI 参考](docs/reference/cli.md) |
| 查环境变量 / settings.json | [环境变量](docs/reference/env.md) · [配置参考](docs/reference/config.md) |
| 搞懂一次 turn 怎么跑完 | [Turn 生命周期](docs/internals/01-turn-lifecycle.md) |
| 接 MCP 服务器 | [MCP 集成](docs/integrations/mcp.md) |
| 出问题 | [故障排查](docs/guides/troubleshooting.md) |
| 了解仓库整体结构 | [架构说明](docs/ARCHITECTURE.md) |
| 看决策记录 | [ADR 索引](docs/adr/README.md) |
| 全部文档索引 | [docs/README.md](docs/README.md) |

## 已知缺口（alpha）

- 只验证 Python 3.13；CI 覆盖 Ubuntu 与 Windows，macOS 未被持续验证。
- 桌面壳目前只构建 Windows NSIS 包，代码签名与自动更新尚未接入。
- 图像输入可用；语音与其它模态归一化拒绝，不做静默降级。
- 未发布到 PyPI，安装只有源码与一键脚本两条路径。
- 对外文档仍在补齐：存量架构文档多为英文，中文为新写文档的默认语言。

## 贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)。设计先行、每个改动带可验证的完成定义；分支与门禁规则在提交前请先读一遍。

## 安全

见 [SECURITY.md](SECURITY.md)。安全问题请走私密通告，不要开公开 issue。

## 许可证

[MIT](LICENSE) © 2026 Ember452
