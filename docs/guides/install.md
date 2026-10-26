# 安装

## 前置条件

| 用途 | 需要 |
| --- | --- |
| 引擎与 CLI | Python **3.13**、[uv](https://docs.astral.sh/uv/) |
| 桌面 / Web 端 | Node **24** 与 npm |
| 本地沙箱（可选） | 已启用的 `srt` 或 Docker（见 [配置参考](../reference/config.md) 的 `sandbox`） |

CI 在 Ubuntu 与 Windows 上跑同一套门禁；macOS 未被持续验证，遇到平台相关问题请附 `doctor` 输出。

## 方式一：从源码（推荐）

当前唯一被持续验证的安装路径。

```powershell
git clone https://github.com/Ember452/questor.git
cd questor
uv sync
uv run python -m questor --help
```

`uv sync` 会创建 `.venv` 并安装 `pyproject.toml` 的运行依赖。要参与开发再加开发依赖：

```powershell
uv sync --extra dev
```

## 方式二：一键脚本

仓库自带安装脚本：

- Windows：`scripts/install.ps1`
- macOS / Linux：`scripts/install.sh`

脚本默认从仓库 `main` 分支读取，因此**仓库必须可公开访问**：

```powershell
iex (Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/Ember452/questor/main/scripts/install.ps1')
```

```bash
curl -fsSL https://raw.githubusercontent.com/Ember452/questor/main/scripts/install.sh | sh
```

脚本支持从源码安装（`-FromSource` / `--from-source`）。若你的网络无法访问 GitHub，
请改用方式一（先拿到仓库副本，脚本在本地同样可执行）。

## 安装后验证

```powershell
uv run python -m questor doctor
```

`doctor` 检查工作区目录、配置文件与凭据是否可用。它通过不代表模型一定连通——
真实连通性在第一次对话时才会暴露。

## 文件放在哪

| 路径 | 内容 | 覆盖方式 |
| --- | --- | --- |
| `~/.questorharness/settings.json` | 全局配置（模型、权限、沙箱、MCP…） | `QUESTORHARNESS_CONFIG_DIR` |
| `~/.questorharness/data/` | 会话、事件日志、缓存 | `QUESTORHARNESS_DATA_DIR` |
| `~/.questorharness/logs/` | 运行日志 | `QUESTORHARNESS_LOGS_DIR` |
| `~/.questor/agent/` | 产品 workspace（个人记忆、网关配置） | `--workspace` 或 `QUESTOR_WORKSPACE` |

完整清单见 [环境变量](../reference/env.md)。

## 网络与镜像

`pyproject.toml` 把阿里云 PyPI 镜像声明为**默认索引**，国内网络下能显著加速首次
`uv sync`。若你在境外网络，它会拖慢同步；此时删掉 `[[tool.uv.index]]` 一节里的
`default = true`（或整节）再执行 `uv sync` 即可回到官方源。

这条设置被放在仓库而非个人环境里，是当前版本已知的对外不友好项；后续会用
`uv.toml` 或环境变量替代，见 [docs/README.md](../README.md) 的待办说明。

## 下一步

- 跑通第一次对话：[快速开始](quickstart.md)
- 装桌面版：[桌面版指南](desktop.md)
