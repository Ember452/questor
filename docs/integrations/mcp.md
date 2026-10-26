# MCP 集成

MCP（Model Context Protocol）服务器给引擎提供额外工具与资源。配置模型在
`src/questorharness/contracts/mcp.py`，加载逻辑在
`src/questorharness/providers/mcp/config.py`。

## 三种传输

| 类型 | 必填字段 | 可选字段 | 含义 |
| --- | --- | --- | --- |
| `stdio` | `command` | `args`、`env`、`cwd` | 在**本机**拉起子进程通信 |
| `http` | `url` | `headers` | 远程 HTTP 端点 |
| `ws` | `url` | `headers` | 远程 WebSocket 端点 |

## 三种添加方式

### 1. 命令行（推荐）

```powershell
# 本机 stdio 服务器
uv run python -m questorharness mcp add filesystem '{"type":"stdio","command":"npx","args":["-y","@modelcontextprotocol/server-filesystem","D:\\work"]}'

# 远程 HTTP 服务器
uv run python -m questorharness mcp add search '{"type":"http","url":"https://example.com/mcp","headers":{"Authorization":"Bearer <token>"}}'

uv run python -m questorharness mcp list
uv run python -m questorharness mcp remove search
```

`add` 的第二个参数就是该服务器的 JSON 配置对象本身（不是外面再包一层 `mcpServers`）。
写入位置是 `settings.json` 的 `mcp_servers`。

### 2. 启动参数 `--mcp-config`

接受 JSON 文件路径、或直接内联 JSON 字符串，可多次指定。适合临时接入、不进配置文件。

```powershell
uv run python -m questorharness --mcp-config .\mcp.json
```

配置文件形状与常见 MCP 客户端一致：

```json
{
  "mcpServers": {
    "filesystem": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "D:\\work"]
    }
  }
}
```

### 3. 直接改 `settings.json`

字段是 `mcp_servers`，值为"名字 → 服务器配置"的对象。手改后建议用 `mcp list` 复核。

## 插件的 MCP 服务器

插件可以自带服务器。加载时以 `插件名:服务器名` 作为键，**不覆盖**同名的手工配置
（`setdefault` 语义）。

## 权限与安全

- MCP 暴露的工具与其他工具走**同一套权限判定**：`denied_tools` / `allowed_tools` /
  路径规则 / 模式三态都适用。MCP 不因为"外部来的"就获得额外信任。
- `stdio` 类型等于"在本机执行一条命令"，它的 `command` 必须有明确来源；不要把不可信
  来源的配置直接加进来。
- `http` / `ws` 类型会把工具参数发到远端；`headers` 里常带凭据，注意不要把配置提交进仓库。
- 想排除所有 MCP 干扰排查问题时，用 `--bare`（跳过 hooks、插件、MCP 与自动发现）。

## 排查

| 现象 | 检查 |
| --- | --- |
| 工具没出现在会话里 | `mcp list` 是否有该服务器；是否加了 `--bare` |
| stdio 服务器起不来 | `command` 能否在终端直接执行；`cwd` 是否正确；`env` 是否缺 `PATH` |
| 远程服务器 401/403 | `headers` 里的 token 是否过期 |
| 配置改了不生效 | 重启会话；配置在启动时加载，不热重载 |

运行时连接状态包含 `connected` / `failed` / `pending` / `disabled` 四态，可用
`--dry-run` 查看解析结果。
