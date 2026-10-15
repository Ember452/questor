# R03 · 状态与持久化实扒参考（打磨 01-state-model.md）

> **只读实扒产物，非实现、非 01 的替代。** 本文只给**增量与坑**，用于打磨 [`docs/design/01-state-model.md`](../design/01-state-model.md)。
> 方法：读全四个参考项目的相关模块，结论一律带 `文件:行号`（相对各自仓库根）。抽样即不成立——凡未直接读到的行不引用。
>
> 扫描范围（本轮）：
> - **hermes-agent-main**：`agent/conversation_loop.py`（`_LoopState`）、`agent/turn_retry_state.py`、`agent/moa_loop.py`、`agent/delegation_context.py`、`hermes_state_common.py`（SCHEMA_SQL/lineage 谓词）、`hermes_state_schema.py`、`hermes_state_rewind.py`、`hermes_state_compression.py`
> - **wuu-main**：`internal/agentthread/`（types/store/communication）、`internal/activity/activity.go`、`internal/agentcontrol/`（mailbox·worker_execution_lease·spawn_slot·tree_freeze·worker_terminal_*）、`internal/compact/`、`internal/session/compaction_note.go`
> - **CowAgent-master**：`agent/memory/conversation_store.py`、`agent/protocol/step_writer.py`
> - **DeepCode-main**：`core/persistence/`（event_repository·serde·coordination_repository·execution_repository）、`core/sessions/`（store·models·transcript·continuation·thread_goal_store）

**读 01 的结论**：01 的**接缝**（单写者/Command-Event/seq/checkpoint/账本/§12 I1–I7）方向正确、已定案部分无需动。本文命中 6 处**字段级缺口**与一批**落地坑**，都属"跑通后再 lock"的未决字段带（01 §6 头部 working-draft 声明、§11 未决），不推翻已定接缝。

---

## 主题 A — LoopState ≠ DomainState ≠ 事件账本（三者要显式分开）

### 现状（01）
§0 已分 `State` / `Transient` 两通道；§7 说"事件是状态转移+流式信号的投影"。缺：三者的**判据**与"opaque provider 续传态"这一类既非纯瞬态、又非模型可见域的字段。

### 增量
- **A-1 循环局部变量就是 Transient 的活样本，别让它渗进 State。** hermes `_LoopState` 把每轮线程状态分三层：固定于本轮（`user_message/messages/system_message`）/ 本轮内被 phase 重绑（`compression_attempts/final_response`）/ 每次迭代重槽（`response/retry_count/api_kwargs`）——`conversation_loop.py:1381-1461`。其中 `retry_count` 每迭代归零、`restart_count` 跨迭代存活直到有响应，正是"防失控续期把 turn lease 无限占住"的**循环控制**，与领域态无关（`conversation_loop.py:1416-1421`）。
  → 01 §0 可加一句判据：**"为跑完这一 turn 而存在的计数器/信号 = Transient，走事件流，不入 State"**，并举 `TurnRetryState`（每 `api_call_count` 新建、一次性守卫+restart 信号，`turn_retry_state.py:9-60`）为范。
- **A-2 加一类持久字段：opaque provider 续传态（模型不产出、不进 reduce 逻辑，但恢复必需）。** DeepCode 只把"可恢复的不透明态 + 安全展示摘要"落盘，且与展示视图分离：`continuation.py:11-33`（`provider_state` deepcopy + `reasoning_summary`）；`transcript.py:52-57` 把它挂在 assistant 记录上再重建。wuu 的 provider replay 也是这套（`ReplayMode = full_request | previous_response_id`，`providers/openai/responses_websocket_test.go:477-905`）。
  → 01 §2 `Message` / §5 `Checkpoint` 需要 `provider_state`（不透明、按 key 命名空间、**reducer 只搬运不解释**）槽位，否则跨 provider 断点续传（Anthropic thinking sig、codex previous_response_id）无处安放。
- **A-3 "内存视图只需与持久转录一致"，权威是持久态。** hermes rewind 开篇即定调：durable transcript 是唯一权威，warm（内存）history 只需与它 agree（`hermes_state_rewind.py:1-4`）；DeepCode 说得更狠——**事件协议只是展示账本**，落盘的是 model-visible history 的投影并可 resume 重建（`transcript.py:1-6`）。
  → 01 §0 可把"State 权威" sharpen 成一句可操作判据：**"回放/恢复永远从持久态出发，内存视图与事件账本都是可丢弃投影"**。

### 坑
- **A-P1 把 delta/瞬态塞进 State**：01 I3 已列，实扒印证这是最易越界处。DeepCode 直接把"每进程从 live workspace 重写、落盘会 stale 日期并抢走会话标题"的 environment-context **跳过不持久化**（`transcript.py:36-39`）——凡"派生自 live 环境"的内容都属此类。
- **A-P2 过度持久化 opaque 态**会撑爆 State（provider_state 常含大 payload）；hermes 对 system_prompt 用**内容寻址去重表**引用而非每行内联（`system_prompts(hash PK)` `hermes_state_common.py:377-380`；迁移注释"move inline prompt snapshots into shared content-addressed table" `hermes_state_schema.py:189`、`1060`）。→ 大对象一律走 hash 引用（对齐 01 I4）。

---

## 主题 B — 事件溯源 vs 快照（01 §11/§9 已定案，补可落地形态）

### 现状（01）
§11 已定：事件溯源为主（append-only `events`+投影）+ turn 边界轻量快照为辅。§9 表清单含 `events(append)`。缺：两类游标、快照与 log 的一致性/权威性、防 ABA、写原子性。

### 增量
- **B-1 明确两类游标，别只用一个 `seq`。** DeepCode `event_log` 同时有：
  - **逻辑 per-thread `sequence`** = `MAX(sequence)+1 WHERE thread_id`（回放/续传游标）——`event_repository.py:21-56`、head 查询 `sequence_head(s)` `80-122`；
  - **物理全局 `rowid`** = 插入序，用作**跨流 changelog watermark**：`newest_row()` / `threads_written_after(rowid)` `event_repository.py:89-112`。
  → 01 §1 `Run.seq` 只有一条游标。建议：SSE `after_seq` 用 per-run 逻辑 seq；"补齐我错过的所有 run"用**全局单调物理序**（或向量钟/Lamport）。并把"全局序"写进 §7 传输续传与 §9 索引。
- **B-2 快照/index 是"可丢弃派生投影"，log 是唯一真相。** DeepCode 落盘模型最干净：JSONL 为 source of truth，`index.db` 是**派生缓存、损坏即静默回退全扫 JSONL**（`store.py:1-24`）。wuu 每变更**同时**写全量快照文件（按 ID upsert、按 Path 重排）与 append 事件（`agentthread/store.go:35-110`）。
  → 01 §9 应写死顺序与权威："**先 append log（原子）→ 再更新 snapshot/index；snapshot 缺失/损坏 → 由 log 重放**"。当前 §11/§9 只说"两种都要有"，未定谁权威。
- **B-3 `recovery_pointers` 的一个可落地候选形态：`{reset, retain}` 指针。** 01 §2 `recovery_pointers` 形态 + §11/§12 I2 都标"未决"。DeepCode 的 compaction checkpoint 就是一条**合成记录**带 `{reset:True, retain:N}`，恢复时 `visible_kernel_history` 取"checkpoint + 其前 N 条原始尾"重放（`transcript.py:132-154`、写入侧 `172-186`）。这正是"轻量指针+取最近快照后重放"（对齐 memory 决策③/I4）的具体字段候选。
  → 建议把 `{reset, retain}` 记为 recovery_pointers 形态候选之一（另一候选仍是 events 日志偏移）。
- **B-4 append-only 增长要配"永不回收的单调水位"防 ABA。** 两家独立做法：hermes `conversation_generations` 计数器**永不 GC，即便该 peer 的所有 session 行都删了**，否则下界写回 1、复用退役身份（`hermes_state_common.py:522-549`）；DeepCode goal 账本用 `seen_goal_ids`/`turn_settlement_ids` 作 **tombstone frozenset**，退役身份不得再 provision（`thread_goal_store.py:46-48,57-62`），并周期写 `THREAD_GOAL_SNAPSHOT` 压账本（`28-31`）。
  → 01 §5/§9 若允许历史修剪/裁剪，必须显式保留"已发号水位"，否则 snapshot 裁剪 + 重放会重发旧 seq/id。

### 坑
- **B-P1 双写漂移**：snapshot 与 event 同时维护必然分叉（wuu/hermes 都有）。判据只有两种：以 log 为准回退扫（DeepCode）或以 durable 为准校验内存（hermes rewind `hermes_state_rewind.py:67-92`）。01 需选一并写进 §9。
- **B-P2 读/写放大**：DeepCode 需增量维护 index 否则每次列表全扫；wuu 每次 upsert **全量重写** threads 文件（小 N 假设，会话大了会退化，`store.go:47-65`）。01 §9 的 `events` + 快照需明确压缩/归档节奏（memory 已提，落成 DDL 约束）。
- **B-P3 序列化往返陷阱**：DeepCode serde 强制 `allow_nan=False` 且时间戳**必须 tz-aware**，否则拒读（`serde.py:10-45`）。→ 01 §9 可加一行"落盘 JSON 禁 NaN/Inf、时间统一 UTC tz-aware"。

---

## 主题 C — checkpoint 结构与 pending_tool_calls 恢复（01 §5 主战场）

### 现状（01）
§5 `Checkpoint{cp_id,seq,turn,kind,state_digest,pending_tool_calls[]}`；恢复不变式="先扫 pending_tool_calls 补合成 tool_result，再续跑"（**读时修复**派）。§2 不变式=tool_use 必配 tool_result。缺：写门保证、resume 语义、幂等投递。

### 增量
- **C-1 更稳的默认是"写门截断"，读时 repair 只做兜底。** CowAgent `StepWriter` 只在每个 `turn_end` 持久化**"每个 tool_use 都已被 tool_result 应答"的最长前缀**，尾部未闭合 tool_use 一律**扣到下一步**——"the store never holds a half-finished tool call"（`step_writer.py:53-64`、`_closed_prefix` 算法 `128-144`）。这样**落盘态永远 role-pair 一致，恢复根本不需要补对**。
  → 01 §5 建议改为两级：**写门=默认**（durable 永远配对闭合，`pending_tool_calls` 只在"两次 flush 之间被 kill"的窄窗口非空）；**读时 repair=兜底**。当前 01 把读时 repair 写成唯一路径，实扒显示更常见、更省事的是写门。
- **C-2 悬空 ask（user 有、无 reply）也是一种 pending，需专门修复。** hermes resume/rewind 会把存储的 `user;user` 对（一次 ask 结束时没 reply、紧接下一次 ask）**合并成一个 turn** 再寻址，否则"warm history 永远比转录少一轮"（`hermes_state_rewind.py:67-71`，issue #115493）。用户中途改口则"**append a role-safe checkpoint + user message 再重试同一逻辑迭代**"（`turn_retry_state.py:58-60`）。
  → 01 §5 `pending_tool_calls` 只覆盖工具；补一条"悬空 user-turn 修复"与"role-safe checkpoint"概念。
- **C-3 增量持久化必须按稳定 id/fingerprint 去重，不能按下标。** CowAgent 用 `id(m)` 身份而非位置，因为 executor **mid-run 就地编辑列表**（sanitizer 增删），index 会漂→重复存或漏存（`step_writer.py:22-25`、`94-98`）；compaction 若替换了 run 的 query，run 起点无从标记→整体交给 `finish()`（`84-92`）。DeepCode 用 `record_fingerprint = (role, content, tool_call ids, tool_call_id)` 与已存集合去重（`transcript.py:82-100,157-189`）。
  → 01 §9 `events`/`messages` append 需带**稳定幂等键**（message_uid / tool_call_id，01 §2/§4 已有 id），明确"按 uid 去重、不按 seq 位置"。
- **C-4 中断/取消 = 冻结整棵子树 + 保留可恢复 partial。** wuu `FreezeWorkerTree`：取消本轮所有在跑 worker 与排队 spawn，**把 partial 结果保留为可 resume 态**，并 gate 嵌套 wake，防"抢跑的 terminal transition 把已取消 parent 重启"；freeze 持续到 `ResolveFrozenWorkerTree`，其间用 `frozen_tree_snapshot` 幂等 claim 结果、ack 终态记录（`tree_freeze.go:19-101`）。mailbox 给 failed/cancelled 但保留全 context 的 run 打 `Resumable=true + ResumeHint`（"原地复活 vs 重开"，`mailbox.go:99-124`）。
  → 01 §5 `Checkpoint.kind` / §3 `TaskNode` 缺"resumable / 子树冻结"语义。建议 TaskNode 加 `resumable: bool`、Run 加"冻结窗口"，取消传播规则进 §6/§3。
- **C-5 恢复不重复干活 = 幂等投递 claim，不是"抑制事件重放"。** hermes `async_delegations` 带 `delivery_state/delivery_attempts/delivery_claim/owner_pid/owner_started_at`（`hermes_state_common.py:582-609`）；wuu 用 `claimAgentResultDelivery`/consumer 迁移保证一次投递。这正呼应 01 I7"已发 Event 不撤销"：重放会重发事件，**靠消费端幂等 claim 去重**，而非不重发。
  → 01 §5 续传需定义"投递幂等键 + claim/consumer 语义"（与 §4 `tool_call_id` 复用）。

### 坑
- **C-P1 半条 tool_use 落盘 → 下游 provider 400**（01 §2 已列不变式，但没讲落盘边界怎么保证；C-1 写门即答案）。
- **C-P2 compaction checkpoint 伪装成 user 角色**：DeepCode 的 summary 记录借 user-role 载体（因那是模型读的形状），但**"分组/标题逻辑不得当真实用户发言"**，故有 `is_compaction_checkpoint` 守卫（`transcript.py:71-79`）。01 §2 若往 `items` 插 summary，必须带显式标记，否则污染会话标题/turn 计数（hermes title lineage 同源坑）。
- **C-P3 修剪破坏修复**：若 compaction 删掉了悬空 ask 的原文，restore 无法补对——`recovery_pointers` 必须能取回被删原文（回扣 01 §2 recovery_pointers 的可恢复性要求）。

---

## 主题 D — 任务树 / 森林 / DAG 字段（01 §3 主战场）

### 现状（01）
§3 `TaskNode{id,parent_id?,kind,deps[],assigned_run_id?,result?}`；决策④"森林+预留 subagent"；I6"DAG v1 预留 v2 再启用"。缺：边类型化、物化路径、汇聚态、委派账本归属。

### 增量
- **D-1 单一 `parent_id` 不够——边必须带类型。** hermes 一个 `parent_session_id` 自引用 FK（`hermes_state_common.py:398,445`）上挂着**四种语义子节点**：branch / compression-continuation / reset / subagent(ephemeral)，靠 `model_config._branched_from/_delegate_from/_reset_from` 标记 + `end_reason` 分类区分，且**谓词必须单一 owner、禁散落重复实现**（"never-patch-predicates #88197"，`hermes_state_common.py:167-246`）。
  → 01 §3 `TaskNode` 只有 `parent_id + kind`。建议加 **`edge_kind`（spawn|branch|delegate|reset|compact…）**或复用 `Source.Kind/ForkMode`（见 D-2），把 01 §11"任务树字段细节未决"落一个候选结构。
- **D-2 加 `path`（物化路径）+ `depth`。** wuu thread 节点用 materialized `Path` + `Depth` + `SourceKind(root|thread_spawn)` + `ForkMode` + `EdgeStatus(open|closed)`（`agentthread/types.go:33-57`），并按 Path 排序（`store.go:62-64`）。hermes 的委派子进程用 **board root path 做 lineage 围栏**（`delegation_context.py:112-162`）。物化路径让"子树枚举/排序/围栏"O(1) 级、免递归。
  → 01 §3 加 `path`（派生、可索引）与 `depth`；§9 `task_nodes` 加 `idx(parent)` 之外加 `path` 前缀索引。
- **D-3 需要"自身跑完、子节点仍活"的汇聚态。** wuu `StatusWaitingChildren`："the thread's run finished its final message but holds delivery while direct children are still live"（`agentthread/types.go:13-16`）。森林/树做汇聚或取消传播时，缺这一态就无判据。
  → 01 §3 `TaskNode.status` 枚举补 `waiting_children`（或 `blocked_on_children`）。
- **D-4 委派/subagent 执行是独立账本，不塞进 `TaskNode.result`。** hermes `async_delegations`（`delegation_id/parent_session_id/state/task_json/result_json/delivery_*`，`hermes_state_common.py:582-609`）与 CowAgent `runs`（`parent_run_id` "lets a whole delegation tree be walked from any node" + `task_id/task_source` 外部句柄用 TEXT **不做 FK**，`conversation_store.py:94-116`）都把"一次可被委派/spawn/调度、可按 id 找回、resume、汇报的工作单元"独立成表。
  → 01 §3 `assigned_run_id?` 只是钩子；明确 **subagent 节点 → 一条 Run/Delegation 记录（§1 runs[] / §4 账本模式）**，`TaskNode.result` 只放产出摘要指针。外部系统句柄（task_id/source）保留 TEXT 不建 FK。
- **D-5 run/task 追踪表与 messages 历史表故障隔离。** CowAgent 把 `runs` 独立成 auxiliary 表，"任何这里的问题（遗留同名表、半升级）只降级 run 追踪，而不把会话历史一起拖垮"（`conversation_store.py:85-93`）。
  → 01 §9 注明"task_nodes/runs 故障不得连带 messages"（对齐 memory 插件故障隔离）。

### 坑
- **D-P1 印证 I6（v1 只用森林、DAG 后置）稳健。** 实扒四家**没有一个在会话树真用带环 DAG**：依赖关系都是"父子 + 标记 + 少量 deps 读校验"。DAG 会暴涨 reduce 无环校验/调度/断点恢复复杂度（01 I6 已述）。建议 v1 `deps[]` **仅做前置条件读校验、不做拓扑调度**，把"跨节点 DAG"彻底留到 v2+。
- **D-P2 lineage ≠ 可见 ≠ 可恢复**。hermes：reset 保留 `parent_session_id`（lineage）但开一条**独立用户可见会话**；picker 可见 = roots+branch+reset（**不含 subagent 子跑与 compression 续接**）（`hermes_state_common.py:233-246`）。01 §1 Session↔Run↔TaskNode 映射需把这三层语义分开，否则 UI 列表/恢复扫描会串。
- **D-P3 从任意节点 walk 全树需 parent + path 双向索引**（CowAgent `parent_run_id`、hermes `idx_sessions_parent`）；只存 parent → 递归查询代价高。

---

## 主题 E — 权限/审批与 lease/exactly-once（喂给 01 §6/§9 与 C12）

### 增量
- **E-1 审批/租约 = 带 holder + expires_at 的短生命周期记录。** 三家一致：hermes `session_turn_leases`/`compression_locks(conversation_id/session_id, holder, acquired_at, expires_at)` + `idx_*_expires`（`hermes_state_common.py:568-580,626-627`）；wuu `activity.Lease{ActivityID,ThreadID,Token}` + `Controller(agent|user|none)` + `State waiting_confirmation`（`activity.go:14-79`）；DeepCode `resource_leases`（claim/heartbeat/release，按 `(thread,turn)` 归组，`coordination_repository.py:307-333`）。
  → 01 §6 `PermissionCtx.decisions` 目前无 TTL/holder。`awaiting_approval` 应可被租约过期回收（否则死锁），审批记录带 holder+expires_at。
- **E-2 跨进程/崩溃下"取消标志是 Transient"要配 durable terminal intent。** wuu `WorkerExecutionActive` = "活 OS 文件锁租约 **OR** 未 ack 的 durable 终态意图"（`worker_execution_lease.go:18-59,218-241`）；租约 sidecar **永不删除**以便所有竞争者锁同一 inode，进程退出即释放（`20-28`）；并有 `lockWorkerExecutionRelease` 屏障防"零延迟终态在排队启动器 ack 之前释放租约"（`152-171`）。
  → 01 C12/天花板条可加实扒脚注：**单机多进程用 OS 文件锁 / DB lease 即可达单写者+恰好一次；跨机排序才需真正的分布式**（呼应 memory"分布式非扩事件可达"）。
- **E-3 spawn 并发用"预留位"防 TOCTOU 超额。** wuu `spawnSlotReservation`：`maxParallel` 是 process-local 上限、非跨进程信号量，靠预留位避免并发 caller 都看到同一空位而超额（`spawn_slot.go:11-61`）。
  → 01 §3/调度注记：并行上限判定需"预留窗口 + 已注册 + 未释放预留"三者合并计数。

### 坑
- **E-P1 单 schema authority 缺失 → 同版本号不同表形**。hermes #94691：`async_delegations` 某列曾只由 delegation 工具的 lazy `ALTER` 提供，导致两个"同 schema_version"库表形不一致、破坏 rebuild/replay；修法=canonical fresh-install DDL 必须与各组件自带 DDL 逐列一致，且**只有一个 `reconcile_state_schema` 幂等 authority**（`hermes_state_common.py:601-609`、`hermes_state_schema.py:1348-1367`；重建用 `BEGIN IMMEDIATE` 持写锁，`801-816`）。
  → 01 §9 写死："唯一 schema authority + 幂等 DDL + 列 reconcile，禁止组件各持 hand-maintained 表形"。
- **E-P2 身份门 fail-closed**。委派子进程/cron 内跑**不得**被误认成 dispatcher-owned worker（会错误 force-add 工具集、把 `kanban_complete` 默认到别人的 task）；hermes 用 ContextVar 标记 + `owned_kanban_task()` 单一谓词 fail-closed（`delegation_context.py:15-104`）。→ 01 §3 subagent 隔离/§6 权限判定需"缺证据即拒绝"。

---

## 落到 01 的具体增量清单（按 01 章节；均为 working-draft 未决带，不动已定接缝）

| 01 位置 | 增量（建议） | 关键证据 |
|---|---|---|
| §0 两通道 | 判据："跑完本 turn 用的计数器/信号=Transient"；权威："恢复永远从持久态出发，内存视图+事件账本=可丢弃投影" | `conversation_loop.py:1381-1461`、`turn_retry_state.py:9-60`、`transcript.py:1-6`、`hermes_state_rewind.py:1-4` |
| §2 Context.items | 新增 `provider_state`(opaque，reducer 只搬运)；summary/checkpoint 记录带显式标记防伪装成 user；派生自 live 环境者不持久化 | `continuation.py:11-33`、`transcript.py:36-39,71-79` |
| §2 recovery_pointers（未决） | 候选形态 A=`{reset,retain}` 指针+保留窗口；候选 B=events 日志偏移；须能取回被删原文 | `transcript.py:132-154,172-186` |
| §3 TaskNode | 加 `edge_kind`(spawn/branch/delegate/reset/compact)、`path`、`depth`、`resumable`；`status` 补 `waiting_children`；`assigned_run_id` 明确指向 §1 runs/§4 账本；subagent 执行独立成记录、外部句柄 TEXT 不 FK | `hermes_state_common.py:167-246`、`agentthread/types.go:13-57`、`conversation_store.py:94-116`、`hermes_state_common.py:582-609` |
| §3 DAG/I6 | 实扒四家均无带环 DAG → v1 严格森林，`deps[]` 仅读校验、不做拓扑调度 | 全四项目会话树结构 |
| §4/§5 Checkpoint | 恢复默认改"写门截断到 closed_prefix"，读时 repair 兜底；补"悬空 user-turn 修复"；续传加投递幂等 claim；取消=冻结子树+保留 partial | `step_writer.py:53-64,128-144`、`hermes_state_rewind.py:67-71`、`turn_retry_state.py:58-60`、`tree_freeze.go:19-101`、`mailbox.go:99-124` |
| §6 PermissionCtx | `decisions` 带 `holder+expires_at`；`awaiting_approval` 可被租约过期回收；身份门 fail-closed | `hermes_state_common.py:568-580`、`activity.go:14-79`、`coordination_repository.py:307-333`、`delegation_context.py:15-104` |
| §7 传输续传 | 区分**两类游标**：per-run 逻辑 `seq`（after_seq 回放）vs 全局单调物理序（跨 run catch-up/watermark） | `event_repository.py:21-56,80-122` |
| §9 持久化映射 | 写死"log 权威→先 append 后更新 snapshot/index→损坏回退重放"；schema 单一 authority+幂等 DDL+BEGIN IMMEDIATE 重建；JSON 禁 NaN/时间 tz-aware；大对象内容寻址去重；防 ABA 永不回收水位；task/runs 与 messages 故障隔离 | `store.py:1-24`、`hermes_state_schema.py:1348-1367,801-816`、`serde.py:10-45`、`hermes_state_common.py:377-380,522-549`、`conversation_store.py:85-93` |

## 与 01 已定案的一致性（无需改，仅印证）
- 事件溯源为主 + turn 边界轻量快照为辅：DeepCode（log 权威+派生 index）、wuu（快照+事件双写）、hermes（append messages）三家各自印证。
- 单写者经 Command→reduce：hermes 用 DB 级 lease/`BEGIN IMMEDIATE` 把"单写者"落到 SQLite；wuu 用 OS 文件锁落"跨进程单 owner"——都是**同机**手段，与 01 C12"跨机分布式是独立硬骨头"不冲突。
- I3 delta 不持久化 / I4 快照=指针 / I6 DAG 后置 / I7 Event 不可反哺：实扒均找到正面范例，无需调整，仅需在 §9 补幂等 claim 使 I7"重放不重复副作用"可执行。

## 未覆盖 / 后续窗口（诚实标注）
- 仅按用户点名范围实扒，未系统扫 DeepCode `thread_repository.py`/`execution_repository.py` 全量与 hermes `hermes_state_compression.py` 内部算法（其 checkpoint/absorb 细节可作 R03b 补）。
- 跨机 exactly-once / 分布式排序四家**都未真正解决**（均为单机 SQLite+文件锁+lease），故本文只能给"同机落地范式"，不能替代 01 C12 的分布式决策。
