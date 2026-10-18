# ADR-0038: 子 agent 本体 = 独立 Run（同进程 asyncio + 跨 run 只经 Command + at-least-once）

- 状态：✅（2026-10-18，P8 开工前置门；实现见 `docs/plan/08-p8-multi-agent-dag.md` T1–T9）
- 背景：`capabilities/subagent/README.md` 明示"sub-agent orchestration (spawn/lease/mailbox, wuu `agentcontrol`-style) and the DAG scheduler are P8"；`contracts/state_schema.py:200` 已预留 `TaskNode.assigned_run_id`（"将来子agent执行绑定"）。P8 必须定夺：子 agent 是**独立 Run**，还是同 run 内的节点扇出？若是独立 Run，状态权威/seq/取消/故障/exactly-once 如何汇而不破单写者（C2）、不越 C12 分布式天花板。
- 决策：
  - **子 agent = 独立 Run**：有自己的 `Run`/`RunController`/Inbox/event log/checkpoint/`PermissionCtx`，父经 `TaskNode(kind=subagent, assigned_run_id=child_rid)` 关联。**v1 = 同进程 asyncio 并发多 run**（`surfaces/run_registry.py` 的 `submit(run_id, …)` 多 active run 管道已就绪，P7 已用）；**跨进程/跨机 = P9/C12 天花板，不越界**。
  - **同进程，不是"扩事件就到分布式"**（C12/天花板条）：子 run 与父 run 共享一个 `InProcessEventBus` + 一个 `SQLiteStore`（`BEGIN IMMEDIATE` 单写者）；`RunRegistry` 注册多个 controller；子 loop 是父 loop 之外的另一个 asyncio 任务。
  - **状态权威与 seq 汇法（不合并、按 run 隔离）**：承 [ADR-0011](./0011-seq-semantics.md) 两游标——每 run 各自 per-run 逻辑 `seq`（SSE `after_seq`），跨 run catch-up 用全局物理 `gseq`（[ADR-0022](./0022-dual-cursor-watermark.md) `watermark()/replay_global()`）。父子事件流按 `run_id` 天然隔离（`InProcessEventBus.subscribe(run_id, …)`）。完整快照各自落（[ADR-0020](./0020-durable-write-gate-and-log-authority.md)）。
  - **跨 run 通信一律 `Command→reduce`（C2/C5/C16，绝不互写字段）**：
    - 父生 = 端口向父 inbox 提 `SpawnSubagent{child_run_id, node_id, spawn_key, child_ctx}`；父 reduce 记账 + 发 `peer_started`（占父 seq）。
    - 子终 = 子 loop 经端口向父 inbox 提 `ReportChildTerminal{child_run_id, node_id, terminal_status, result_ref?}`；父 reduce 回填 node + 发 `peer_ended`。
    - 父向子下达 = 经注入的 `CommandRouterPort` 向子 inbox `submit`（如 `Cancel`）。**没有任何一处做 `child_run.<field> = …` 的跨 run 直写**（源码级判红守，DoD②）。
  - **spawn 时序（reduce 纯函数、不建 run）**——对齐 [ADR-0028](./0028-pairing-gate-and-provider-fault-normalization.md)/`WriteMemory` 的"reduce 发事件、消费点做 IO"：端口先**预生成 `child_run_id` + 投影 `child_ctx`（子⊆父，见 ADR-0040）+ fan-out gate 判定（见 ADR-0041）**，超发直接拒不提交；reduce 受理成功后端口才 `register` 子 `RunController` 并起跑子 loop。replay/重投同 `spawn_key` → reduce 判重 → **不产生第二个子**。
  - **取消传播 = 冻结子树 + 保留 partial（不 out-of-band 硬杀，C7）**：父 `Cancel` 后，loop 读 reduce 后 `task_tree`、经 `CommandRouterPort` 向每个未终态子 inbox 提 `Cancel(reason=owner)`；子 reduce 走既有 `Cancel` 分支回填自身 open `tool_use`（C18/C19）后落 `run_cancelled(cancel_reason=owner)`；父 `RunController.close()`，迟到 `ReportChildTerminal` 得 `REJECTED_TERMINAL`（**不复活已取消父**，消解 wuu `tree_freeze.go` 所述"子终态与父 freeze 竞态重启已取消父"）。partial 权威由子自身 checkpoint 承载（`resumable` 语义经 `assigned_run_id`+`list_unfinished_runs`+`peer_ended.resumable_hint` 组合达成，不新增字段）。
  - **故障隔离（C10）**：子 run 的 provider/工具异常按 ADR-0028 在**子自己的 loop** 归一为子 `run_failed`，绝不穿出带崩父；父只观察 `peer_ended(terminal=failed)`，不共享异常栈。
  - **exactly-once 的真实语义（诚实标注）**：v1 = **at-least-once + 去重键**——去重靠 inbox `idempotency_key`（[ADR-0013](./0013-run-command-inbox.md)/[ADR-0016](./0016-tool-lifecycle-approval-identity.md)，`spawn_key`/`request_id` 命名空间），复用 hermes `subagent_lifecycle.py:286/442` 的 correlation/result_hash 判据。**崩溃重启不留孤儿子**：`StorePort.list_unfinished_runs()`（ADR-0022）枚举非终态 run，父 `--resume`（[ADR-0021](./0021-cross-process-resume.md)）后扫 `assigned_run_id` 指终态但未 ack 者幂等 `ReportChildTerminal` 回填。**完整 claim/delivery_state 持久账本 = P9**（[ADR-0021](./0021-cross-process-resume.md) 已把这套重方案后置 P9；本 ADR 不重演"把 P9 的账塞进 P8"）。
  - **载荷边界（C18/C20 + ADR-0019）**：`peer_started/peer_ended.data` 只带关联键（`parent_run_id/child_run_id/node_id`）+ 有界 `status/terminal_status` + `result_ref`（artifact 指针）+ `resumable_hint`；**委派正文/prompt/args/raw 结果绝不内联进事件流或日志**；`node_updated` 白名单 `{node_id,status,title,parent_id}` 不扩（`objective` 不外发、`title` 须为短标签）。若未来跨进程 spawn，沿用 P5 做法：stderr/子进程关联**显式注入 `run_id`**，不假装 `contextvar` 能过边界（`docs/pitfalls.md` 第 3 条）。
- 后果：
  - 正面：DoD"两 agent 协作完成一任务"达成且可证伪（父事件流拿子终态、无旁路写）；子获得真独立终止/独立权限上下文/独立账本；seq/快照/resume 全复用既有 ADR，不新造游标；C2 单写者经"跨 run 只经 Command"结构守住。
  - 代价/需持续守：多 run 交织使 `--resume`/投影更复杂 → 必须扩 `check_replay_determinism`（`_canonical` 加 `task_tree` + 顺序无关 fixture，见 plan §6）；`CommandRouterPort`/`SubagentSpawnerPort` 的抽象在 `contracts`、实现在 L6/L3，组合根注入（C1/S7 内核零依赖不破）。
  - 边界：跨进程 exactly-once（lease/claim/DB 锁）明确不做（C12/天花板）；深度 fan-out 默认 1（ADR-0041）。
- 备选（被否）：
  1. **同 run 节点扇出**：把"子独立终止/独立权限上下文/独立账本"挤进单 run，违 C2 per-run 单写者与 C7 终止粒度、且 `assigned_run_id` 成死字段 → 否。
  2. **跨进程子 run + 现在就上 DB lease/exactly-once**：单机 `BEGIN IMMEDIATE` 已保证单写者，跨机排序是独立硬骨头（C12），提前做拖累 → 否，后置 P9。
  3. **集中消息总线（照 MetaGPT `publish_message`）**：第二真相 + 破 per-run 单写者 → 否。
- 关联：HARD-CONSTRAINTS C2/C5/C7/C10/C12/C13/C16/C18/C20；ADR-0011/0013/0016/0019/0020/0021/0022/0028；`docs/design/01-state-model.md` §3/§13(:192)、`docs/design/02-event-protocol.md` §7；`docs/pitfalls.md` 第 3/5 条；`docs/plan/08-p8-multi-agent-dag.md` §4.1；peer：wuu `agentcontrol/{tree_freeze,spawn_slot,mailbox}.go`、hermes `subagent_lifecycle.py`（MIT，改造取形状）。
