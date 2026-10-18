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
| `run_started` | 受理 SubmitMessage | run_id, `policy_ref`?(P9/ADR-0045 additive、不 bump `v`) | 否 |
| `turn_started` | 每轮开始 | turn | 否 |
| `text_delta` | 可见文本流式分片 | delta | 否（**不持久化**） |
| `reasoning_delta` | 推理流式分片 | delta | 否（不持久化） |
| `message_completed` | 一条 assistant 消息定稿 | message(完整块) | 否 |
| `tool_started` | 工具发起 | tool_call_id, name, args_summary | 否 |
| `tool_progress` | 工具中间进度 | tool_call_id, message | 否（不持久化） |
| `tool_completed` | 工具返回 | tool_call_id, status, result?, display? | 否 |
| `approval_request` | 权限=ask 且审批请求已落账 | request_id, tool_call_id, name, args_summary, risk, reason, expires_at | 否（进入 per-call awaiting_approval） |
| `approval_resolved` | 人工/超时/取消裁决一个 request | request_id, tool_call_id, decision, decided_by, resolved_at | 否 |
| `permission_mode_changed` | `SetPermissionMode` 成功变更未来模式 | mode, changed_by, effective_from_turn | 否 |
| `node_updated` | 任务树节点状态变 | node_id, status, title, parent_id | 否 |
| `peer_started` | 父 spawn 子 agent（P8，ADR-0042） | parent_run_id, child_run_id, node_id | 否 |
| `peer_ended` | 子 agent 达终态回父（P8，ADR-0042） | parent_run_id, child_run_id, node_id, terminal_status, result_ref?, resumable_hint | 否 |
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
- **P3 落定**（详见 [ADR-0021](../adr/0021-cross-process-resume.md)）：`/resume` 为跨进程续跑触发（`rebuild_run` + 交回唯一 loop，仅重派 OPEN 调用）；`after_seq` 重放的“不丢不重”在真 socket 层验收（durable 走 `seq`、delta 不占 durable seq）。

## 5. Command 集（输入事件，均经 CommandInboxPort→reduce）
`SubmitMessage`、`ProposeAction`（策略的单步意图：调工具/收尾）、`MarkToolValidated`、`RequestApproval`、`ResolveApproval(allow|deny, request_id)`、`ExpireApproval`、`SetPermissionMode`、`MarkToolRunning`、`RecordToolResult`、`MarkToolDenied`、`Cancel(reason ∈ {user|timeout|budget_exhausted|no_progress|safety|owner})`、`WriteMemory`、`RequestCompactHint`(仅 advisory，不强制)。
- surfaces 只向对应 active run 的 Command Inbox 提交；不得直接调用 reduce（ADR-0013/C16）。
- 每个 Command 有来源与幂等键；重复/终态后/队满提交返回明确 receipt，不生成 durable event。审批以 `request_id` 为幂等边界，同 request 同 decision 为 no-op，异 decision 拒绝（ADR-0016）。
- 每个 Command → reduce 校验不变式 → 新 State + 发 Event[]；非法 Command 被拒并发错误事件（不靠上层自觉）。

## 6. 兼容与版本规则
- **只加**：新 `type`、`data` 新**可选**字段；消费者忽略未知。
- **禁**：改/删既有 type/字段语义、把可选变必填、复用废弃 type 名。外部事件**完整 args**与内部路径/env 明细不属于公开契约。
- 破坏性 → `v` 升版 + 投影层做兼容转换；CI 对每个外部 type 的 data schema 做字段级快照，不只比较 type 集。
- `protocol/event.schema.json` 采用 `type → $defs payload schema` 的 `oneOf`；每 payload `additionalProperties:false`。新增可选字段先 schema、再代码、再 TS codegen。

## 7. 生长场景验收（证明"只增不改"够用）
语音附件→`voice_attached`（P6 已移除、仍作协议纪律例证，ADR-0036）；**子agent→`peer_started/peer_ended`+`node(kind=subagent)` 已于 P8 定形（[ADR-0042](../adr/0042-peer-event-additive-shape.md)，additive、不 bump `v`）**；产物→`artifact`；MCP 热增→`tools_changed`（**P9/ADR-0046 定形：live-only 告警、`domain∈{tools,skills,mcp,plugins,settings}`、不占 durable seq、不 bump `v`**）；预算→`budget_update`。**均不碰信封/关联键/终止序**——若某扩展逼着改这三样，即协议设计错。

## 8. 待定（v0 后锁，C11）
- 每事件的**精确 data 字段**：先给上面核心集，跑通 2-3 个策略变体后 lock。
- 编码先 **JSON**；量大再评估压缩/二进制帧。内部事件全集随 04-turn-loop 细化时补齐。

## 9. 落地补充（评审采纳）
- **E2 终态唯一性**：靠 **reduce 串行化 + first-writer-wins**，一轮**至多一条终态事件**；并发终止按优先级择一（默认 用户取消>安全告警>超时>预算耗尽，**可配置**）。严禁同时下发 `run_cancelled`+`run_failed`。
- **E1 resync 流程**：收到 `resync_required` 后客户端必须 ①丢弃本地 UI 态 ②拉当前 run 完整快照 ③从最新 `seq` 重新订阅 SSE。归入 §4。
- **E3 审批幂等**：`ResolveApproval` 可能被 SSE 重复投递，**reduce 层幂等丢弃已处理的审批**，不靠前端。
- **E4 版本覆盖嵌套**：`v` 的"只增不改"不只管信封顶层，`data` 内嵌对象字段同样受管。
- **T2 乱序**：外部事件**到达顺序≠业务顺序**；并行工具返回乱序属正常，客户端按 `tool_call_id`/`seq` 归组渲染，**不靠 SSE 到达序**。
- **X2 存储**：`events` 表**只存内部事件**；外部事件是运行时投影、**不入库不存两份**；回放=重放内部事件再投影。
- **X5 OpenAI 兼容=投影适配器**：把 Questor 事件翻译成 OpenAI SSE 形状；**内核状态/权限/账本不为它简化**。

## 10. 评审增补（R02/R08；只增不改，不触信封/关联键/终止序三根硬骨）
- **事件完备性**：补 `item_started`/`item_removed`（在途条目撤销）· `text_replace`/`reasoning_replace`（provider 整体改写、live-only）· `message_completed.phase`（commentary|final，一轮可多条）· `reasoning_delta.channel(summary|trace)+source`· `turn_queued/steered/held`（中途插话，配 §5 `Steer/Enqueue`）· `warning`（非终态告警，承 §0-3）· `compact_started/applied`· `thread_started/resumed/updated`· `usage_delta.response_ordinal`· `tools_changed` 加 `domain(skills|plugins|mcp|settings)`。
- **投影**：内部至少**三层**（provider-stream / kernel-domain → 外部）；`hidden` 可见位 + 投影产物**脱离内部实例的拷贝**；raw/normalized 双轨（**兼容判定只赖 normalized**）；外部集之上每 surface 再二次投影（信封 `surface`；IM 合并限流属投影层职责）。
- **seq/续传**：`resync_required` 分因 `{expired|ahead|unknown_request|version_mismatch}`+边界 seq；**delta/heartbeat 不占 durable seq**（走 item offset、live-only）；终态 `run_completed` 与传输 `stream_end` 两标记、取消只在下个 checkpoint 生效有尾窗；溢出→`replayRequired`（丢 notification 不触发全量 resync、丢 durable 才）；**Command 进入 reduce 受理时占 durable seq**（早失败也能落终态；仅入队 receipt 不另存一份真相）；重写/压缩发 `baseline_seq` 栅栏。
- **版本**：续传前**版本闸门**（不符→resync，禁新版本解旧事件）；契约版本≠策略版本；一次性 `capabilities` 协商；**每 Command 携幂等键、reduce 去重、变更类 default-never 自动重放**；禁 NaN/Inf+单帧字节上限。
- **OpenAI 兼容映射表**：标准字段走 OpenAI 语义、专有收进扩展位（如 `x_questor`）、无原生续传（断连=取消、`[DONE]` 终结）、错误编进 `finish_reason`；**内核三终态不因兼容面简化**。
- **投递幂等**（→ ADR-0011）：终态/工具事件配**稳定投递 id**、claim-then-deliver；**投递/claim 视图从事件重放重建、不落第二份真相**。
