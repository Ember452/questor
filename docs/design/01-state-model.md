# Questor 核心状态模型（L1 Domain/State）

> 设计文档，非实现。承接 [`00-layering.md`](./00-layering.md) 的 L1，并落实四条最优决策：
> ① 策略接口=单步意图、计划进状态；② 权限决策模型一等；③ 传输 HTTP+SSE、断点游标入状态；④ 任务树=森林、预留 subagent。
> 定位：这是 **Harness 全程唯一可信状态**，所有组件经命令/归约读写它；事件协议是它变更的投影（见 §7）。
> **⚠ 本文是 working draft**：接缝（run/seq/Command-Event 总线/权限决策模型/工具账本骨架）**早锁**；具体字段（任务树细节/断点粒度/记忆指针形态）**跑通 2-3 个策略变体后再 lock**（防过早焊死，见 [HARD-CONSTRAINTS.md](./HARD-CONSTRAINTS.md) C11）。

---

## 0. 设计约束（先立规矩）
- **单写者**：只有 Kernel(L2) 经"命令→归约"改状态；策略/UI/工具都是提交意图，不直接改字段。
- **两类通道分离**：
  - `State`：权威·可序列化·可回放·可断点 —— 本文定义。
  - `Transient`：取消标志 / 在途流式 delta / 进度心跳 / 单次调用局部变量 —— **不进 State**，走事件流(L2→L6)。
- **不变式优先**：违反不变式（§2 配对、§4 账本完整）的命令被拒。
- **只读视图靠 COW/持久化结构，不靠浅 `frozen`**：策略拿的是**按字段暴露的只读视图**（看不到断点/权限/内部元数据），用 copy-on-write/结构共享做到"不可变但不每轮全量深拷贝"（[HARD-CONSTRAINTS](./HARD-CONSTRAINTS.md) C2/C3）。全量快照只在**回放/分支试验**时生成。

## 1. 顶层容器

```
Session        一个长期会话（用户可见的一条对话线）
 ├─ session_id, created_at, defaults(model/locale/permission_mode)
 └─ runs[]     每次"用户发起→agent 完成/取消" = 一个 Run

Run            一次执行（断点/回放/续传的单位）
 ├─ run_id
 ├─ seq            本 run 单调事件游标（续传/断点用，决策③）
 ├─ turn           当前 turn 序号
 ├─ status         idle|running|awaiting_approval|cancelled|failed|completed
 ├─ budget         max_turns / token / wall-clock 上限
 ├─ context        §2 会话上下文
 ├─ task_tree      §3 任务树（森林）
 ├─ tool_ledger    §4 工具调用账本
 ├─ checkpoints    §5 断点
 ├─ permission_ctx §6 权限上下文
 └─ error_stack    §8 错误栈
```

---

## 2. 会话上下文 Context
消息序列 + 压缩边界。

| 字段 | 类型 | 可空 | 写 | 读 | 持久 |
|---|---|---|---|---|---|
| `items[]` | Message 列表(user/assistant/tool/system) | 否 | Kernel | 策略/传输 | ✅ |
| `compaction_floor` | int | 是 | Kernel(压缩时) | 恢复器 | ✅ |
| `summary` | 摘要文本（对已压区） | 是 | Kernel | 策略(拼prompt) | ✅ |
| `recovery_pointers[]` | 指向被压原文的引用 | 是 | Kernel | 检索回读 | ✅ |

- **Message 项**：`id, role, content_blocks[], created_at, seq`；`content_blocks` 支持 `text / reasoning / tool_use / tool_result / image / file`。
- **不变式**：`tool_use` 必有配对 `tool_result`（否则下游 provider 400）——§6。
- **压缩**：只压中段、**user/assistant 文本不删**，删的进 `summary`+`recovery_pointers`（可恢复，对齐 hermes）。

## 3. 任务树 TaskTree（森林，决策①④）
计划进状态，不是接口。策略每步可增删节点；一个节点可 kind=subagent（v1 只占位）。

```
TaskNode {
  id, parent_id?,            # 森林；顶层任务 parent=null
  kind: task | subagent,     # v1 只用 task；subagent 结构预留
  title, objective,
  status: pending|active|blocked|done|failed|cancelled,
  deps[],                    # 依赖的其它 node（构成 DAG）
  assigned_run_id?,          # 将来子agent执行绑定
  result?                    # 该步产出摘要
}
```
- **写**：Kernel 调度器（由策略提交的"计划意图"命令归约而来）。**读**：策略(决定下一步)/UI(展示进度)/断点。
- **与单步接口的关系**：策略每 turn 读森林 + 上下文，返回**一个**意图（做哪个节点/调哪个工具/收尾）；Kernel 执行、回填 node、发事件。计划是"多步"的，接口是"单步"的，二者靠这棵树解耦。

## 4. 工具调用账本 ToolLedger
每次工具调用一条，可审计、可重放、可关联事件。

```
ToolCall {
  tool_call_id,        # 关联键，跨事件稳定
  turn, node_id?,      # 属于哪个 turn / 任务节点
  name, args,
  status: pending|running|success|error|critical_error|denied,
  result?, display?,   # 给模型的 result / 给人的 display
  permission_decision?,# 见 §6
  started_at, ended_at?, elapsed?,
  seq_request, seq_result
}
```
- **写**：Kernel 工具路由（发起时 pending，结束回填）。**读**：UI 卡片/持久化/策略。
- 取消时未完成的调用**必须回填一条 error 结果**，保证 §2 配对不变式不破。

## 5. 断点 Checkpoint（决策③）
run 的可恢复快照点。

```
Checkpoint { cp_id, seq, turn, kind: auto|manual|pre_tool|post_tool|pre_compact,
             state_digest,                      # 指向该点状态（存快照或增量日志）
             pending_tool_calls[] }             # 中断时未闭合的 tool_use，供回填
```
- **续传**：客户端带 `after_seq` → 服务端从最近 `cp` 起重放 `seq>after` 的事件；`cp` 之前的状态直接取快照。
- **快照节奏**：turn 边界必打（单步接口的天然一致点）；重工具/压缩前后各一个。
- **恢复不变式**：恢复时先扫 `pending_tool_calls` 补合成 tool_result，再续跑。

## 6. 权限上下文 PermissionCtx（决策②，一等）
```
PermissionCtx {
  mode: default|plan|full_auto,
  rules[]: {pattern, action: allow|ask|deny, scope},   # 二维通配
  denylist[]: 不可被 mode/rules 覆盖的敏感路径          # 如凭据 .env
  decisions[]: {tool_call_id, decision: allow|ask|deny, decided_by: rule|user, at}
}
```
- **决策是纯函数**（引擎判定），**审批**（ask 时）产生 `awaiting_approval` 状态 + 一条 HITL 事件；**执行/封装**在 Kernel 与工具执行器。沙箱后端(seatbelt/bubblewrap)是**可插拔实现**，v1 可先"受限执行"、后补。
- 不变式：`deny` 命中直接拒且**不计入失败重试**；`denied` 也要写进 ToolLedger（审计）。

## 7. 变更与事件的关系（投影模型）
```
策略意图 / 外部命令
      ▼
  Command（输入事件 / 唯一写入口，可序列化）
      ▼
  reduce → 新 State + 发出 Event[]
      ▼
  Event（输出事件）= { v, seq, run_id, type, data }   # 见 02-event-protocol.md
```
- **状态类事件**（对齐断点、可回放）：如 `tool_completed`、`node_status_changed`、`run_cancelled`。
- **流式/瞬态事件**（不落状态）：`text_delta`、`reasoning_delta`、`tool_progress`、`heartbeat`。
- 这条即"事件是状态转移+流式信号的投影"，也是**先定状态再定事件**的依据。

## 8. 错误栈 ErrorStack
统一 envelope，不散落。
```
ErrorEntry { seq, at_turn, layer(kernel/tool/provider/persist), code, message,
             retryable:bool, cause?, context? }
run.error_stack: ErrorEntry[]
```
- 各阶段 catch → 归一成本 envelope；重试/fallback 读 `retryable`；终态失败时最后一条进 `run_failed` 事件的 `data.error`。

## 9. 持久化映射（设计级，非最终 DDL）
StorePort→SQLite：`sessions / runs / messages(+content) / task_nodes / tool_calls / checkpoints / events(append) / permission_rules`。
- `events` **append-only** + `seq` 索引 → 支撑续传/回放。
- 记忆(三层/Deep Dream)是**另一套**（长期知识），不进本运行态；本 run 只持有 context 与指针。

## 10. 四条决策 → 状态落点（自检）
| 决策 | 在本文的落点 |
|---|---|
| ① 单步接口 + 计划进状态 | §3 任务树森林 + §7 Command |
| ② 权限一等、沙箱可插拔 | §6 PermissionCtx + ToolCall.permission_decision |
| ③ HTTP+SSE 续传 | Run.seq + §5 Checkpoint(after_seq) + §9 events append-only |
| ④ 预留多agent | §3 TaskNode.kind=subagent + assigned_run_id |

## 11. 已定 / 未决 / 下一份
- **已定**：存储走**事件溯源（append-only `events` + 投影）为主、turn 边界快照为辅**——天然支持续传/回放/审计，与 §7 投影模型自洽；快照做读加速。
- **已定**：写记忆/状态一律 `Command→Harness→StorePort`；读（含向量检索）走 Harness 持有的 `StorePort` 接口，策略无裸句柄（C4）。
- **未决（v0 后锁）**：任务树字段细节、断点粒度、recovery pointer 具体形态。
- **天花板提醒**：远程策略/分布式 Harness 不是"扩事件"就到——跨机排序/租约/exactly-once 是独立硬骨头（C12 + 天花板条）。策略默认进程内，经 `PolicyPort` 预留远程可能，不提前为此序列化一切。
- **下一份**：`docs/design/02-event-protocol.md`——把 §7 的事件投影正式化成协议（信封、核心事件、内外分层+版本、只增不改铁律、三适配器）。

---

## 12. 落地不变式与边界（评审采纳，与 HARD-CONSTRAINTS 呼应）
- **I1 不变式在 reduce 内部强制**：如 TaskNode 提交→reduce 校验 **DAG 无环**；`tool_use` 提交→校验账本配对。非法 Command 由 reduce 拒绝 + 产 error 事件，**不靠上层策略自觉**。
- **I2 压缩属 Kernel 行为**：触发(token超限/turn 阈值/溢出)由 Harness 控制；策略只能**读**压缩后 `summary`，最多发一个"上下文压力"**advisory 提示**，**不能发强制压缩命令**。`recovery_pointers` 形态（指向 events 日志偏移 vs 独立消息 ID）影响原始消息恢复，v0 后定。
- **I3 瞬态 delta 绝不持久化**：`Message`=完整最终块才写 `context.items`；`text_delta/reasoning_delta`=SSE 传输分片，**不落状态、不持久化**。UI 调试严禁图省事把 delta 塞进 state（最易越界，对应 C2/C5）。
- **I4 快照=轻量投影+指针**：turn 边界生成轻量 `Domain_State` 快照，可只存 seq 游标/引用而非全量消息拷贝；**恢复=取最近快照 + 重放其后 append-only 事件**。两种机制都要有，别只做一种。
- **I5 mode/权限变更=Command、不回溯**：mode 属 `Command`走 reduce；**已发生的 tool_call 历史 decision 不重算**，只对**未来调用**生效（否则审计/回放的 decision 会漂移）。
- **I6 TaskTree v1 只用森林**：父子层级即可；**DAG 跨节点依赖只预留、v2 再启用**（DAG 会暴涨 reduce 校验/调度/断点恢复复杂度）。
- **I7 Event 不可反哺**：只有 Command 改状态（C5）；回滚只回 Domain_State、**已发 Event 不撒销**（C10）。

## 13. 评审增补（R03/R06；均为 working-draft 未决带，不动已定接缝）
- `Message` 加 `provider_state`（opaque、reducer 只搬运不解释，供跨 provider 断点续传）；summary/checkpoint 记录带**显式标记**（勿伪造成 user）；派生自 live 环境的不持久化。
- **recovery_pointers 定为 `(seq_from, seq_to) + CoveredHash 锦`**（指向 events 单调序号区间，非字节偏移/非 UUID）；读前校验锦、历史漂移 **fail-closed**。
- 权威判据："恢复永远从持久态出发，内存视图+事件账本=可丢弃投影"。
- **两类游标**：per-run 逻辑 `seq`（after_seq 回放）+ 全局单调物理序（跨 run catch-up/watermark）（→ ADR-0011）。
- Checkpoint：默认**写门截断到 closed_prefix**（durable 永不半 tool_use）、读时 repair 兜底；补悬空 user-turn 修复；投递幂等 claim；取消=冻结子树+保留 partial（`resumable`）。
- TaskNode 加 `edge_kind(spawn|branch|delegate|reset|compact)/path/depth/resumable`、status 补 `waiting_children`；subagent 节点→独立 Run/Delegation 记录（外部句柄 TEXT 不 FK）；**DAG v1 严格森林、deps 仅读校验**。
- §9 持久化写死：log 权威→**先 append 后更新 snapshot/index**→损坏回退重放；**单一 schema authority + 幂等 DDL + `BEGIN IMMEDIATE` 重建**；JSON 禁 NaN/Inf、时间 UTC tz-aware；大对象内容寻址去重；防 ABA 永不回收水位；task/runs 与 messages 故障隔离。
