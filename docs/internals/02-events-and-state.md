# 02 · 事件与状态

引擎的对外产物只有一种：**事件流**。宿主（TUI、行式 REPL、桌面渲染层、HTTP 客户端）
消费事件渲染界面；状态的修改走另一条路。

定义在 `src/questorharness/contracts/domain/events.py`，全部是 `frozen dataclass`——事件
一旦发出就不可变，谁都不能回头改它。

## 七种事件

| 事件 | 关键字段 | 含义 |
| --- | --- | --- |
| `AssistantTextDelta` | `text` | 增量文本，边生成边发 |
| `AssistantTurnComplete` | `message`、`usage` | 本轮 assistant 消息完成 |
| `ToolExecutionStarted` | `tool_name`、`tool_input` | 即将执行工具 |
| `ToolExecutionCompleted` | `tool_name`、`output`、`is_error`、`metadata` | 工具执行结束 |
| `ErrorEvent` | `message`、`recoverable` | 需要展示给用户的错误 |
| `StatusEvent` | `message` | 瞬时系统状态（重试、钳制、压缩提示） |
| `CompactProgressEvent` | `phase`、`trigger`、`message`、`attempt`、`checkpoint` | 压缩进度 |

`StreamEvent` 是以上七种的联合类型。

### CompactProgressEvent 的 phase

```text
hooks_start            → context_collapse_start → context_collapse_end
                       → session_memory_start   → session_memory_end
                       → compact_start          → compact_end
                       → compact_retry | compact_failed
```

`trigger` 取值 `auto`（每轮开始自动检查）、`manual`（用户触发）、`reactive`（提示词超长后
被动压缩）。

## 事件流的水位线

`run_query` 每次产出的是一个二元组：

```python
(event, usage_snapshot_or_None)
```

只有 `AssistantTurnComplete` 与部分错误事件带 usage。宿主按需统计成本，引擎不替它记账。

## 为什么事件不能改状态

这是本仓的核心不变式之一（见 [AGENTS.md](../../AGENTS.md) 与 [CONVENTIONS](../CONVENTIONS.md)）：

- `Event` 是**输出**：描述"发生了什么"，供展示与审计；
- `Command` 是**唯一写入口**：改状态必须走命令，命令是同步的、可测试的、可重放的。

如果允许事件反哺状态，同一条流被重放两次就可能得到两个结果，断点续传和审计都会失真。

## 谁会看到这些事件

| 宿主 | 消费方式 |
| --- | --- |
| 全屏 TUI | 按事件类型分区渲染（对话区、工具卡、状态栏） |
| 行式 REPL | 事件转成逐行输出，`--output-format json/stream-json` 直接序列化 |
| 桌面 / Web | 引擎事件转成线协议消息（HTTP + 事件流），渲染层订阅 |
| 渠道（飞书 / QQ） | 事件聚合后映射为消息卡片 |

宿主差异只在渲染，**事件语义对四者完全一致**——这是"多端共享一套协议"的实际含义。

## 观察事件的两个实用入口

```powershell
uv run python -m questorharness --print "..." --output-format stream-json
uv run python -m questorharness --dry-run
```

前者输出完整事件流（适合脚本与调试），后者只打印解析后的运行时配置，不产生对话事件。
