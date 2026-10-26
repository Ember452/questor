# 03 · 工具与权限

工具有两件事要搞清楚：**什么时候允许跑**（权限），**跑挂了怎么办**（容错）。
判定逻辑在 `src/questorharness/capabilities/policy/checker.py`，执行与容错在
`src/questorharness/engine/query.py` 与 `src/questorharness/engine/tool_execution.py`。

## 权限判定的顺序（重要）

`PermissionChecker.evaluate()` 按固定顺序短路，顺序本身就是安全边界：

| 顺序 | 检查 | 结果 |
| --- | --- | --- |
| 1 | 内置敏感路径匹配 | **无条件拒绝**，任何模式、任何配置都改不了 |
| 2 | `denied_tools` | 拒绝 |
| 3 | `allowed_tools` | 放行 |
| 4 | `path_rules` 中 `allow=false` 的规则 | 拒绝 |
| 5 | `denied_commands`（命令用 fnmatch 匹配） | 拒绝 |
| 6 | 模式 = `full_auto` | 放行 |
| 7 | 工具是只读的 | 放行 |
| 8 | 模式 = `plan` | 拒绝（plan 只读） |
| 9 | 其余 | 不放行，**要求确认** |

两个容易踩的点：

- **第 1 条永远优先**。即使用户写了 `allowed_tools: ["read_file"]`，读 `~/.ssh/id_rsa` 也会被拒。
- **第 3 条在白名单里就直接放行**，不再看路径规则——这是"显式允许优先"的取舍，
  所以不要在 `allowed_tools` 里放能读任意路径的工具。

### 内置敏感路径

```text
*/.ssh/*                       */.aws/credentials        */.aws/config
*/.config/gcloud/*             */.azure/*                */.gnupg/*
*/.docker/config.json          */.kube/config
*/.questorharness/credentials.json
*/.questorharness/copilot_auth.json
```

用 fnmatch 匹配**完全解析后的绝对路径**。目录型工具（`grep`、`glob`）传进来的可能是一个
目录根，判定时会额外尝试"带尾斜杠"的形式，这样 `*/.ssh/*` 也能拦住直接指向 `~/.ssh` 的调用。

### 三种模式

| 模式 | 只读工具 | 变更型工具 |
| --- | --- | --- |
| `default` | 放行 | 需要用户确认 |
| `plan` | 放行 | 拒绝（先出方案再动手） |
| `full_auto` | 放行 | 放行 |

`--dangerously-skip-permissions` 会跳过整套检查，**只在一次性容器或沙箱里用**。

## 沙箱是另一层，不替代权限

权限是**逻辑层**：决定"这次调用允不允许"。
沙箱是**执行层**：决定"就算允许了，它在什么边界里跑"（可用域、挂载、资源限制）。

两者都要开才有纵深：权限挡住不该做的，沙箱限制做错时的破坏半径。配置见
[配置参考](../reference/config.md) 的 `sandbox` 一节。

## 工具执行的容错

| 情况 | 行为 |
| --- | --- |
| 工具抛异常 | 转成 `is_error=True` 的 `ToolResultBlock`，继续循环；日志记录异常类型与 id |
| 并发多工具时单个失败 | `gather(return_exceptions=True)` 保住其它兄弟协程的结果 |
| 工具未注册 | 走同一套错误结果路径，不抛到循环外 |

**为什么必须这样**：会话里一个 `tool_use` 没有配对的 `tool_result`，下一轮请求会被协议
层直接拒绝。所以宁可返回一个错误结果，也不能让结果缺席。

## 加一个新工具要动哪里

1. 工具本体与能力声明：`src/questorharness/capabilities/tools/`
2. 注册：同一包下的 registry（AGENTS 路由表有精确行）
3. 若涉及新的危险能力（写盘、执行、网络），补 `docs/CONVENTIONS.md` 要求的注释与测试
4. 若改变了权限语义，先写 ADR，再改代码

工具携带的元数据（`tool_metadata`）会被压缩链路保留，所以新增字段要能被序列化。
