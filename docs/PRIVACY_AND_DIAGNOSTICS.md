# 隐私与诊断

Questor 是一个**能读写本地文件、执行命令、访问网络**的 Agent。这份文档说明：数据落在哪、
什么会离开本机、出问题时怎么取证而不泄露敏感信息。

## 数据落在哪

| 路径 | 内容 | 敏感度 |
| --- | --- | --- |
| `~/.questorharness/settings.json` | 模型、权限、沙箱、MCP 配置（**可能含 api_key 字段**） | 高 |
| `~/.questorharness/credentials.json` | 凭据存储 | 高 |
| `~/.questorharness/data/` | 会话快照、事件日志、缓存 | **含完整对话与工具输出** |
| `~/.questorharness/logs/` | 运行日志 | 中高（可能含路径、命令、片段） |
| `~/.questor/agent/` | 产品 workspace：`soul.md`、`user.md`、个人记忆、网关配置 | 高（个人画像） |

这些目录默认都在 `.gitignore` 里，不会因为你在仓库目录下运行就被提交。

## 什么会离开本机

只有三条路径，且都需要你配置或启用：

1. **模型请求**：发往当前 profile 的 `base_url`。请求体包含系统提示词、对话历史、
   工具结果——也就是模型"看到"的一切。
2. **网络工具**：启用 web 搜索 / 抓取时，请求发往搜索端点或目标站点；走代理时经
   `web.proxy`。
3. **MCP 服务器**：你添加的服务器。`stdio` 类型会在**本机执行命令**，`http` / `ws`
   类型会把请求发到对应 URL。

要观察真实出站行为，把 `QUESTORHARNESS_WEB_PROXY` 指到一个你能看流量的代理，或用系统
防火墙记录 `questorharness` 进程的连接。

## 凭据保护

- 内置敏感路径（`~/.ssh/`、云厂商凭据、`~/.questorharness/credentials.json` 等）在
  **任何权限模式下都拒绝**，不受 `allowed_tools` 或 `path_rules` 影响。
- 凭据不要写进仓库文件、不要粘贴进对话；用环境变量或 `questorharness auth` 管理。
- 日志与事件里可能出现密钥形态的字符串，提交 issue 前必须脱敏。

## 诊断三件套

```powershell
uv run python -m questor doctor             # 工作区与凭据是否就绪
uv run python -m questorharness --dry-run   # 解析后的配置/技能/命令/工具，不执行
$env:QUESTORHARNESS_LOG_LEVEL = "DEBUG"     # 提高日志级别后复现
```

引擎加 `--debug` 等价于提高日志级别。日志文件在 `~/.questorharness/logs/`。

## 分享诊断信息前

1. 只贴**必要片段**，不要整份日志；
2. 删除 API key、token、Cookie、Authorization 头；
3. 删除私有路径（用户名、内网主机名、项目名）；
4. 删除对话正文——它可能是你最不该公开的部分。

## 彻底清理

```powershell
Remove-Item -Recurse -Force "$HOME\.questorharness"
Remove-Item -Recurse -Force "$HOME\.questor"
```

这会同时删掉配置、凭据、会话与记忆，不可恢复。只想清会话就删 `data/` 下的会话目录。
