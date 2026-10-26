# 01 · Turn 生命周期

入口是一个异步生成器：`run_query(context, messages)`，源码在
`src/questorharness/engine/query.py`。它不断产出 `(StreamEvent, UsageSnapshot | None)`，
直到模型不再请求工具、出错、或触及 `max_turns`。

## 一张图

```text
run_query
  └─ while 未超 max_turns
       ├─ 1. 输出上限钳制（必要时吐一条 StatusEvent）
       ├─ 2. 自动压缩检查（微压缩 → 全量摘要）
       ├─ 3. 图像预处理（非视觉模型把图片转成文本）
       ├─ 4. 调模型，边流边翻译成事件
       ├─ 5. 校验最终消息（空消息丢弃）
       ├─ 6. 追加 assistant 消息，发 AssistantTurnComplete
       ├─ 7. 没有 tool_use？→ 跑 STOP hook，结束
       └─ 8. 有 tool_use？→ 串行/并发执行 → 结果回填成 user 消息 → 下一轮
```

## 逐步说明

### 1. 输出上限钳制

`max_tokens` 会先被上下文窗口的安全上限钳制。真的被改小时，第一轮吐一条
`StatusEvent` 说明原因——用户看到的是解释，不是静默改动。

模型如果回 400 抱怨 `max_tokens` 超限，引擎会解析出供应商支持的上限、调整后**重试同一轮**
（`turn_count` 回退一位），而不是把错误抛给用户。

### 2. 自动压缩

每轮开始先估算 token 量。超阈值时：

1. 先做**微压缩**：清理旧工具结果的正文，保留结构与元数据；
2. 仍然超，再做**全量摘要**：交给模型压缩较早的消息。

压缩过程通过 `CompactProgressEvent` 流式上报（`auto` / `manual` / `reactive` 三种触发）。
如果模型直接报"prompt too long"，引擎会做一次强制压缩后重试；**只重试一次**，避免死循环。

### 3. 图像预处理

非视觉模型的会话里出现图片块时，预处理阶段把图片转成文字描述，而不是让请求失败。

### 4. 调模型

一次请求带上：模型、消息、系统提示词、钳制后的输出上限、`tool_registry.to_api_schema()`、
`effort` 档位。流式事件被翻译成引擎事件：

| provider 侧事件 | 引擎事件 |
| --- | --- |
| `ApiTextDeltaEvent` | `AssistantTextDelta` |
| `ApiRetryEvent` | `StatusEvent`（含重试次数与等待时间） |
| `ApiMessageCompleteEvent` | 内部最终消息 + `UsageSnapshot` |

### 5. 空消息

模型返回空的 assistant 消息时，引擎**丢弃该轮**并报错退出一轮——继续往会话里塞空消息会让
下一轮请求更难自洽。

### 6. 落地本轮

assistant 消息进入 `messages`，立刻发 `AssistantTurnComplete`（带本次 usage）。

### 7. 没有工具调用 = 本轮结束

跑一次 `STOP` hook（`stop_reason=tool_uses_empty`）后返回。控制权回到宿主。

### 8. 有工具调用

- **单个工具**：串行执行，`ToolExecutionStarted` → 执行 → `ToolExecutionCompleted`。
- **多个工具**：先全部发 `ToolExecutionStarted`，再并发执行。并发用
  `gather(..., return_exceptions=True)`——单个工具炸掉不能取消兄弟协程，否则会话里会留下
  没有对应结果的 `tool_use` 块，Anthropic 协议会直接拒绝后续请求。

工具抛异常不会中断循环：异常被转成 `is_error=True` 的 `ToolResultBlock`，照样回填。

结果以 `role="user"` 的 tool_result 消息追加，进入下一轮。

## 边界与失败语义

| 情况 | 行为 |
| --- | --- |
| 达到 `max_turns` | 抛 `MaxTurnsExceeded` |
| 网络 / 超时 | `ErrorEvent`（`recoverable=True`）后结束本轮 |
| 其它 API 错误 | `ErrorEvent` 后结束本轮 |
| 模型流没有最终消息 | `RuntimeError`——这是协议级不一致，不该静默 |
| 工具抛异常 | 转成错误结果，继续循环 |

## 谁在调用它

- 引擎 TUI / 行式 REPL：`src/questorharness/bootstrap/`
- 产品应用：`src/questor/runtime.py` 走同一套 `run_terminal_repl`，只换系统提示词、
  会话后端与记忆后端
- 桌面壳：通过回环宿主间接驱动同一引擎

三者的差别只在**注入什么**，不在循环本身。
