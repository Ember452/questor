# Questor 事件协议（L0 Contracts + L6 Surfaces）

> 承接 [`01-state-model.md`](./01-state-model.md) §7 的投影模型与 [`HARD-CONSTRAINTS.md`](./HARD-CONSTRAINTS.md) C5/C6。
> 定位：**Harness 对外的唯一契约 + 系统内部总线**。所有前端（桌面/Web/移动/IM/OpenAI 兼容）都只吃这份协议。设计文档，非实现。

---

## 0. 三条铁律（不可破）
1. **只有 Command 改状态；Event 不得反哺为状态输入**（否则破坏单写者）。
2. **Command=输入事件**（可校验、可拒绝、非 append-only）；**Event=输出事件**（append-only、发出不可撤回、是状态变更之后的产物）。二者同处一条带类型总线，但语义分开。
3. **内部事件 ≠ 外部事件**：对外只暴露**投影后的精简稳定集**；消费者遇**未知 `type` 静默忽略**——**但错误类事件除外，未知的 error 事件至少告警**。

## 1. 信封
```
{ v, seq, run_id, turn?, ts, type, data }
```
- `seq`：每 run 单调 → 续传/回放游标；`v`：契约版本（只增不改；破坏性变更才 bump + 兼容转换）。
- **关联键**（定了永不改/改名）：`run_id / turn / tool_call_id / card_id / item_id`。

## 2. 内部总线 → 外部投影
```
Kernel 内部事件(细粒度、私有、可随实现演进)
   │  e.g. node_status_changed / ledger_entry / compact_applied / reduce_rejected
   ▼  显式投影层(映射表 + 字段白名单 + 截断)
外部事件集(带版本 v、精简、稳定、只增不改)  ── 桌面/Web/移动/IM/OpenAI兼容 只订阅这个
```
- 好处：Harness 内部重构不外泄、不炸旧客户端；对外契约才是"要守兼容"的对象。

## 3. 外部事件 v0（type → 触发 → data 关键字段 → 是否终态）
| type | 触发 | data（关键字段） | 终态 |
|---|---|---|---|
| `run_started` | 受理 SubmitMessage | run_id | 否 |
| `turn_started` | 每轮开始 | turn | 否 |
| `text_delta` | 可见文本流式分片 | delta | 否（**不持久化**） |
| `reasoning_delta` | 推理流式分片 | delta | 否（不持久化） |
| `message_completed` | 一条 assistant 消息定稿 | message(完整块) | 否 |
| `tool_started` | 工具发起 | tool_call_id, name, args_summary | 否 |
| `tool_progress` | 工具中间进度 | tool_call_id, message | 否（不持久化） |
| `tool_completed` | 工具返回 | tool_call_id, status, result?, display? | 否 |
| `approval_request` | 权限=ask | tool_call_id, name, args, risk | 否（进入 awaiting_approval） |
| `node_updated` | 任务树节点状态变 | node_id, status | 否 |
| `usage_delta` | 用量更新 | tokens, cost? | 否 |
| `heartbeat` | 长任务保活 | ts | 否 |
| `run_cancelled` | 取消 | final? | **先于 completed** |
| `run_failed` | 失败 | error{code,message,retryable} | 是 |
| `run_completed` | 正常收尾 | final, usage | 是 |

- **终止序**：`run_cancelled` 先于 `run_completed`；一轮**必有且仅有一个**终态事件。
- **delta vs 完整块**：`*_delta` 只做实时显示、绝不入状态；定稿走 `message_completed`/`tool_completed`。

## 4. 传输绑定（对齐 ADR-0007）
- HTTP + SSE：`data: {json}\n\n`，行首 `id: <seq>`；`POST /run`、`/cancel`、`/resume`。
- 重连带 `Last-Event-ID`/`after_seq` → 从最近快照重放其后事件；游标过期回 `resync_required`。

## 5. Command 集（输入事件，均经 reduce）
`SubmitMessage`、`ProposeAction`（策略的单步意图：调工具/收尾）、`ResolveApproval(allow|deny)`、`Cancel(reason: user|timeout|safety)`、`WriteMemory`、`RequestCompactHint`(仅 advisory，不强制)。
- 每个 Command → reduce 校验不变式 → 新 State + 发 Event[]；非法 Command 被拒并发错误事件（不靠上层自觉）。

## 6. 兼容与版本规则
- **只加**：新 `type`、`data` 新**可选**字段；消费者忽略未知。
- **禁**：改/删既有 type/字段语义、把可选变必填、复用废弃 type 名。
- 破坏性 → `v` 升版 + 投影层做兼容转换；CI 对外部契约做 schema 快照 diff。

## 7. 生长场景验收（证明"只增不改"够用）
语音附件→`voice_attached`；子agent→`peer_started/peer_ended`+`node(kind=subagent)`；产物→`artifact`；MCP 热增→`tools_changed`；预算→`budget_update`。**均不碰信封/关联键/终止序**——若某扩展逼着改这三样，即协议设计错。

## 8. 待定（v0 后锁，C11）
- 每事件的**精确 data 字段**：先给上面核心集，跑通 2-3 个策略变体后 lock。
- 编码先 **JSON**；量大再评估压缩/二进制帧。内部事件全集随 04-turn-loop 细化时补齐。
