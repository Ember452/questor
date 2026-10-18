# Phase P8 详细计划 — 多 agent / 子 agent + DAG

> 起手**必读**：[`AGENTS.md §4.5`](../../AGENTS.md) · [`docs/ROADMAP.md §1/§1.5`](../ROADMAP.md) · [`docs/design/HARD-CONSTRAINTS.md`](../design/HARD-CONSTRAINTS.md)
> **§0 未填完 = 本 Phase 计划未就绪、不能开工**（ROADMAP §0 硬门槛）。
> 本文是 READ-ONLY 规划产物：定稿后**不自动开工**，先做对抗式评审（§8 前置门），Blocker/Major 全关才建 worktree 分支进入实现。
> **对抗式评审（已执行）**：两路并行——①契约完备性/不变式破坏、②范围漂移/安全边界/权限继承/载荷外泄。结论=**通过**；1 个 Major（spawn 层界与时序，防 C1 越层 + reduce 纯函数）**已在 §4.1 收口**并落进 ADR-0038。实现于 worktree `questor-p8-multi-agent-dag`、分支 `feat/p8-multi-agent-dag`（基线 691 passed）。
> 状态：`docs/plan/08-p8-multi-agent-dag.md`，基于 `main` HEAD `754021b`（PR #147 合入 ADR-0036）。下一个 ADR 编号 = **0037**。

---

## 0. Peer-Repo 扫描（**必填**，AGENTS §4.5 · 综合取优）

**现场重列 `project-main/` 目录**（`Get-ChildItem`，2026-10-18 实测，12 个兄弟仓，剔除 `questor*` worktree 与 `build/编码`）：
`Agent-S-main / autogen-main / cordis-main / CowAgent-master / crewAI-main / DeepCode-main / EvoFlow-main / GenericAgent-main / hermes-agent-main / MetaGPT-main / OpenManus-main / wuu-main`。
> `questor-p6-drop` 已不在磁盘（worktree 已 prune）；规范工作区 = `questor/`（main）。**cordis 的 DI/Fiber 生命周期属 P9 参照，本 Phase 不提前引**。

**许可核验（ADR-0031 免署名，但许可类型仍逐仓核）**：MIT = wuu / hermes / MetaGPT / OpenManus / DeepCode / GenericAgent / cordis（可安全改造复用）；Apache-2.0 = Agent-S（改码须守 NOTICE 义务，本 Phase 只用其设计、不搬码）；CC-BY-4.0 = autogen（代码引用需谨慎，本 Phase 取设计口径）；crewAI / CowAgent 首行非标准 SPDX，**若真要搬码先读全文再定**；**EvoFlow evopanel = PolyForm Noncommercial，只读设计、绝不搬码进 MIT 仓**。

| 能力 | 扫描仓（`file:line`） | 结论 | 复用/改造说明 · 许可/边界注意 |
|---|---|---|---|
| 子 agent 本体 = 独立 run + spawn/lease/mailbox | **wuu** `internal/agentcontrol/agent_control.go:1,81,87-105`（`maxParallel`+`spawnReservations`+`queued[]preparedSpawn`+`workerLeases`）；**hermes** `agent/subagent_lifecycle.py:269-323`（in-process 子、`launch→SubagentHandle`） | 改造（取形状，不搬传输） | 子=独立 Run 经 `assigned_run_id` 关联。wuu 是 Go+跨进程 lease，我们只借 **spawn 预留在 spawn 前防超发** 的形状，落 `contracts`+`kernel`。守 C1：编排机制在 L3 `capabilities/subagent`。 |
| fan-out 宽度上限（防超发） | **wuu** `spawn_slot.go:11-61`（reservation 桥接 spawn 前窗口，`running+pending>=maxParallel` 拒） | 改造复用 | 关键洞见：`maxParallel` 是 **control-local、非跨进程信号量**（跨进程靠 lease）——v1 单机正好对上"run 级 asyncio 并发"。 |
| 取消 = 冻结子树 + 保留 partial(resumable) | **wuu** `tree_freeze.go:26-102`（`FreezeWorkerTree`：取消 live worker + queued spawn、保留 resumable partial、**gate 嵌套结果唤醒防终态与 freeze 竞态重启已取消父**）；`mailbox.go:103-117` `isResumableMailboxStatus` | 改造（取语义，去持久 claim 账本） | 我们 v1：父 `Cancel` → 向每个未终态子 inbox 提 `Cancel(owner)`，父不再向子提新 Command；partial 由子自身 checkpoint 承载。`claimAgentResultDelivery` 这套持久 claim → P9（承 ADR-0021）。 |
| 权限继承收缩（子⊆父） | **hermes** `subagent_lifecycle.py:471-473`（`allowed_toolsets` 非父 `enabled_toolsets` 子集则拒："would broaden parent permissions"）、`:231-232`（always blocks unsafe child tools） | 改造复用（判据） | 直接对上 point 7。我们落 `PermissionCtx` 投影函数：`mode` 保守默认、`rules⊆父`、`denylist=父∪{新}`、floor 同 OS。 |
| spawn 幂等 / at-least-once 去重 | **hermes** `subagent_lifecycle.py:286-290`（`correlation_id` 同父去重）、`:442`（`result_hash`=sha256 去重键）；**wuu** `worker_terminal_ack.go`/`delivery.go` | 自写（借判据）+ 边界诚实 | v1 = **at-least-once + inbox `idempotency_key`**（复用 ADR-0013/0016 现成机制）；完整 claim/delivery_state 账本 → P9（ADR-0021:4/8/14 已定后置）。 |
| 孤儿子 run 重启对账 | **wuu** `startup_reconcile.go` / `worker_terminal_recovery.go`；**ADR-0022** 已给 `list_unfinished_runs()` | 改造复用（用现成原语） | 用 `StorePort.list_unfinished_runs()`+`watermark()` 枚举非终态 run，父 resume 后对 `assigned_run_id` 指终态但未 ack 者幂等回填 `ReportChildTerminal`。 |
| DAG / flow 状态机（拓扑） | **crewAI** `flow/types.py:57-90`（`ExecutionMethodData` initial_state/final_state/status）；**OpenManus** `flow/planning.py`；**DeepCode** `core/schedule/scheduler.py` | 自写（**只用 reduce 校验，不引调度器**） | I6 冲突裁决见 §3/ADR-0037：P8 **只做依赖校验（环/悬空/终态唯一）+ 读侧就绪判定**，不引外部 flow DSL/调度器——那会破坏单步 PolicyPort 接口（design/05）+ 违 C11。 |
| 委派消息总线（mailbox/消息投递） | **MetaGPT** `environment/base_env.py:124,175`（`publish_message` 集中分发）；**autogen** runtime 多 agent 消息 | 自写（**拒绝集中总线**） | 集中总线 = 第二真相 + 破 per-run 单写者（C2/C5/C20）。委派一律经 `Command→reduce`（父 inbox / `ReportChildTerminal`），消息正文走 ADR-0019 有界 artifact 指针、不进事件流。 |
| 有界结果 / artifact 指针 | **hermes** `subagent_lifecycle.py:25-29`（goal 16K/result 32K/metadata 8K）；**wuu** `result_artifact.go`/`artifact_import.go` | 复用 ADR-0019 | `peer_ended.data` 只 `{关联键, status, result_ref?, resumable_hint}`，**正文/args/raw 不进事件**（C18/C20）。 |
| 前端（任务树多 agent 视图） | 同栈优先 **DeepCode** `desktop/web`+`src-tauri`（React/Tauri v2）、**EvoFlow** `evopanel`（只读设计，禁搬码） | 改造（瘦客户端） | **本 Phase 不强制交付桌面新 UI**（P7 已合入）；若加，仅消费 `peer_*/node_updated`、零业务下沉（C14/ADR-0007）。 |

> **结论**：P8 主复用源 = **wuu agentcontrol（MIT）** 的 spawn 预留/冻结子树/孤儿子对账形状 + **hermes subagent_lifecycle（MIT）** 的权限子集判据/句柄防伪/at-least-once 去重。DAG 取**reduce 内校验**（自写、落 `state/reduce.py`，对齐 ADR-0004"I1 在 reduce 强制"），**拒绝**外部 flow 引擎与集中消息总线。

---

## 1. 目标与可验证判据（DoD）

- **进入条件**（ROADMAP §1 P8 行）：**P4**（记忆 v1，已合入）。不依赖 P6（ADR-0036 移除）/P7/P5。现状：`TaskKind.SUBAGENT`、`TaskStatus.WAITING_CHILDREN`、`TaskNode.deps/assigned_run_id` 均为已落契约的占位（`contracts/state_schema.py:131,138,199-200`）；`capabilities/subagent/README.md` 明示"spawn/lease/mailbox + DAG scheduler = P8"。
- **一句话目标**：让**两个真 Run 协作完成一个任务**，父经事件流拿子终态、无旁路写；同时把 `deps` 字段从"存在但无消费者"升级为"reduce 强校验"。

### DoD（可复现行为 + 判据；区分 已验证 / UNVERIFIED）

| # | 判据（可复现） | 验证方式 | 档位 |
|---|---|---|---|
| ① | 父 run 策略提 `ProposeSpawn` → 内核建**独立子 Run**（同进程 asyncio），父 `node_updated(kind=subagent, status=active)` + `peer_started{parent_run_id,child_run_id,node_id}`；子 run 有独立 `RunController`/Inbox/event log/checkpoint | 集成测试：脚本化 provider，断言父事件流含 peer_started、`child_run_id≠parent_run_id`、子在自己账本落 `run_completed` | **已验证**（脚本化 provider） |
| ② | 子终态经 `ReportChildTerminal` Command 回灌父 reduce → 父发 `peer_ended{child_run_id,terminal_status,resumable_hint}`；**无跨 run 直接字段写**（C2） | 集成：开 2 个并发 `/events` 订阅者跑父+子，断言每 seq 恰一行（承 pitfalls #5）；源码级断言父侧改状态只来自 Command | **已验证** |
| ③ | 构造**环依赖 / 悬空依赖 / 自环**，reduce **判红拒收 + 发错误事件、不崩**、非法 `deps` 不落 `task_tree` | 单元 + `check_replay_determinism` 新 fixture：非法 DAG 命令→`WARNING`/error 事件且状态不变 | **已验证** |
| ④ | **权限继承收缩**：子 `PermissionCtx` = `mode` 保守默认 + `rules⊆父` + `denylist⊇父` + floor 同 OS；试图放宽被拒（"would broaden parent permissions"） | 单元：断言子 denylist 是父超集、子 rules 是父子集、子对同一工具 ask 不因父 full_auto 降 allow | **已验证** |
| ⑤ | 父 `Cancel` → 未终态子树收敛（每子收 `Cancel(owner)`、回填自身 open tool_use、partial 保留），**不 out-of-band 硬杀** | 集成：父跑、中途父 Cancel，断言每个 live 子落 `run_cancelled(cancel_reason=owner)` 且子 tool_ledger 配对完整 | **已验证** |
| ⑥ | **spawn exactly-once（v1 真实语义 = at-least-once + 去重）**：同一 `spawn` 幂等键二次提交**不**产生第二个子 run；崩溃重启不留孤儿子（`list_unfinished_runs` 检出 + 幂等 `ReportChildTerminal` 回填） | 单元 + 集成：重投同键断言 DUPLICATE；模拟 kill 父后 `--resume` 断言子终态回灌一次 | **已验证（同进程/单写者）**；**跨进程 exactly-once = UNVERIFIED（后置 P9）** |
| ⑦ | `--resume` 多 run 交织后正确：子 run 交错顺序**不影响父回放结果** | `check_replay_determinism` 新 fixture（见 §6）：交换子 Command 提交顺序、断言父 `_canonical` 一致 | **已验证（同进程）**；真多机 = UNVERIFIED |
| — | 真 LLM / 真远程 MCP server / 真开窗口驱动多 agent | —— | **UNVERIFIED，不冒充**（本机无头/无凭据不跑，与 P5/P7 口径一致） |

---

## 2. 本 Phase 不做（范围纪律，§11）

1. **P9**：OpenAI 兼容 API、cordis 式 DI/插件宿主/热插拔、**跨进程 exactly-once lease/claim/delivery_state 账本**、远程/多机策略（C12 天花板）。
2. **P10**：可恢复压缩、评测回归网、observability 刀 3（追踪面板 / `questor logs` / OTel）。
3. **绝不"顺手把 P6 多模态加回来"**（ADR-0036 已整阶段移除；`全 src` 对 `voice|audio|tts|asr|vision|modalit` 零命中）。按需扩展走 L5 provider / L6 surface 接缝，不占 Phase 编号。
4. **RAG / 知识库**：`SCALE-ESTIMATE §6` 维持"先不做"。
5. **桌面端只消费事件协议**：编排/spawn/cancel/mailbox **一律不下沉 Shell**（C14 / ADR-0007）。
6. **不启用完整拓扑调度器**：reduce 只做 DAG **校验 + 读侧就绪判定**；**不做**内核主动 fan-out/fan-in 派发（会破坏单步 `PolicyPort` 接口，design/05；C11）。
7. **不扩** `TaskNode` 的 `edge_kind(spawn|branch|delegate|reset|compact)/path/depth/resumable`——这些属"真上拓扑调度器/分支/重置"时代；P8 加即违 C11。
8. **不启用** `TaskStatus.WAITING_CHILDREN`——父观察子终态走 `ReportChildTerminal`+`peer_ended`，不靠 fan-in 节点态。
9. **不做工具级 reader/writer gate 与真并发派发**——见 ADR-0039，P8 只落"子代理 fan-out admission gate"（run 级），工具 gate 正交、再推后一次。
10. **不越界跨进程/跨机 subagent**（v1 同进程 asyncio 多 run；跨进程/机 = P9/C12）。

---

## 3. 前置 ADR 门（ADR-0037 起；**ADR 未落册则对应子任务不许开工**）

> 依 ROADMAP §5 + AGENTS §5.5：**跨阶段功能移动 / I6 语义修订 / 契约扩面**属难回退决策，先 ADR 后文档。编号从 **0037** 起（0036 已被 PR #147 占用）。

| ADR | 标题（拟） | 裁决内容 | 守住的点 | 阻塞的子任务 |
|---|---|---|---|---|
| **0037** | I6 语义修订 + P8 DAG 启用范围 | 把 `design/01:181` I6 从"v1 严格森林、DAG v2 再启用"改为**"v1 森林拓扑 + reduce 强制依赖校验（无环/无悬空/无自环/终态唯一）+ 读侧就绪判定；拓扑调度器与 `edge_kind/path/depth` 后置"**。就地修订 I6 + §3 + §12/§13，**消除"文档说 v2、代码在 P8 做"漂移** | I6 / ROADMAP §5 / C11 | T4（DAG 校验）、T0 |
| **0038** | 子 agent 本体 = 独立 Run（同进程 asyncio + 跨 run 只经 Command + at-least-once） | 子=独立 Run 经 `assigned_run_id` 关联；seq 走 ADR-0011 两游标、快照 ADR-0020、`--resume` ADR-0021/0022；**取消传播=冻结子树+保留 partial、经 `Cancel` Command 不硬杀**；spawn v1 = **at-least-once + inbox `idempotency_key` 去重**、孤儿子 `list_unfinished_runs` 检出；载荷边界（正文走 ADR-0019 指针、不进事件/日志） | C2/C7/C10/C12/C16/C18/C20 | T1/T2/T3/T5/T6/T9 |
| **0039** | 并行 gate 归口再决（工具 reader/writer gate 后置、P8 只落子代理 fan-out gate） | 接住 ADR-0029 悬置：**子代理 fan-out admission gate 归 P8**（wuu `spawn_slot` 式 maxParallel）；**工具 reader/writer gate 与真并发派发**显式再推后（归 P10 或独立立项），点名"字段存在 ≠ gate 存在"隐债 | ADR-0029 / ROADMAP §5 / C19 | T6（fan-out gate） |
| **0040** | 子权限继承收缩（fail-closed + 命名空间审批） | `PermissionCtx` 投影：`mode` 强制保守默认（不继承父宽 mode）、`rules⊆父`、`denylist=父∪{新}`、capability floor 同 OS 不放宽（ADR-0015）；子 `ask` 归子自审（父不代答、可 `Cancel` 强制 deny）；`request_id` 命名空间 = `{child_run_id}:…` 跨 run 唯一（ADR-0016）；**策略层无裸句柄**（C4/C8） | C4/C8/C9/C17 / ADR-0014/0015/0016 | T7 |
| **0041** | fan-out 预算与失控终止 | 新增可选 `Budget`（或 `FanoutBudget`）字段：`max_parallel_children`（默认 4）、`max_tree_depth`（默认 1，父不直接生孙）；用量 `usage_delta` **归 per-run** 不汇聚父；终止优先级对齐 E2：**取消>安全告警>超时>预算**，父超预算→父终态+递归 `Cancel` 子树 | C7/C13 / design/02 §9 | T1/T6/T13 |
| **0042** | 事件 additive：`peer_started`/`peer_ended` 定形（不 bump `v`） | 只增两 type（承 design/02 §7 预留名）+ `EXTERNAL_EVENT_FIELDS` 显式白名单；`node_updated` 白名单 `{node_id,status,title,parent_id}` **不扩**；协议计数 20→22、**`EVENT_SCHEMA_VERSION=1` 不动**（additive 先例 ADR-0024/0035）；三处 lockstep + `check_protocol_schema --self-test` fixture 扩面；**C20**：`peer_*` 正文不进 `projection._DATA_KEYS` | C6/C15/C18/C20 / ADR-0035 | T1/T2/T8/T10 |

> **T0 = ADR 门**：ADR-0037~0042 全部落册（可先 draft、随实现转正）后，T1 起才允许动代码。缺 ADR 的子任务视为未就绪。

---

## 4. 子任务分解（T0…Tn；每条配判红用例，先红后绿）

> **依赖是真依赖**（点名 ADR-0029 的坑：**"字段存在 ≠ gate 存在"**——`deps`/`assigned_run_id`/`WAITING_CHILDREN` 早在契约里躺着，但没有 reduce 消费者 = 死字段；`parallel_safe` 同理）。所以 T4（reduce 校验）必须真把 `deps` 接上、T3 的 `SpawnSubagent` 必须真消费 `assigned_run_id`，否则就是重演隐债。

| T | 目标 | 涉及层 | 依赖 | 验证方式 | commit 粒度 |
|---|---|---|---|---|---|
| **T0** | ADR-0037~0042 落册（draft 即可）+ 就地修订 `design/01` I6/§3/§12/§13 + `design/02 §7` 注记 `peer_*` 由"预留名"转"已定义" | docs | — | 文档自检 + ROADMAP §5 口径一致 | `docs(adr): open ADR-0037..0042 for P8 + revise design/01 I6` |
| **T1** | 契约扩面：`EventType.PEER_STARTED/PEER_ENDED`；`contracts/events.py` 加 `PeerStartedData/PeerEndedData`（frozen、有界）；`EXTERNAL_EVENT_FIELDS` 两条显式白名单；`Budget`/`FanoutBudget` 加 `max_parallel_children/max_tree_depth`（可选、默认 None=不 fan-out）。**`TaskNode` 字段不动 → 快照 schema 保持 v3、`store_schema_version` fail-closed 语义不放松** | L0 | T0 | 冷导入 + `check_protocol_schema`（暂缺 schema→预期红，T2 补）+ checkpoint round-trip | `feat(contracts): additive peer_started/peer_ended types + fan-out budget fields` |
| **T2** | wire 契约单一真源：`protocol/event.schema.json` 加 `enum` 两项 + `$defs` 两体（`additionalProperties:false`、有界 `maxLength`）+ `if/then` 两支；TS codegen 重生成 | L0/protocol | T1 | `check_protocol_schema --check` 绿 + `--self-test` 能判红 | `feat(protocol): peer event $defs + regen TS codegen` |
| **T3** | `state/reduce.py` 新增分支：`SpawnSubagent`（幂等 claim `(node_id, spawn_key)`→置 `assigned_run_id`+node active+发 `peer_started`）、`ReportChildTerminal`（回填 node.status/result_ref+发 `peer_ended`+`node_updated`）、`UpdateTaskTree`（承接 L4 意图 `ProposePlanUpdate`→**首次让 reduce 处理 task_tree**，写入前调 T4 校验）。注：`ProposeSpawn/ProposePlanUpdate` 属 `PolicyIntent`(L4)，经内核映射为上述 `Command`，reduce 只见 Command | L1 | T0/T1/T4 | reduce 单测 + `check_replay_determinism` | `feat(state): reduce spawn/report/update-tree branches over task_tree` |
| **T4** | DAG 校验器 `_validate_task_dag`（reduce 内 I1）：无环/无悬空 `deps`/无自环/`node_id` 唯一/终态唯一；非法 → 拒 + `WARNING`（或 `reduce_rejected` 内部事件），**不改 task_tree、不崩** | L1 | T0 | 单元 + `check_replay_determinism` 非法-DAG fixture | `feat(state): DAG invariant (acyclic/dangling/self-edge) enforced inside reduce` |
| **T5** | `contracts/ports.py` 加抽象 `SubagentSpawnerPort`（建子 Run + 注册 RunController）与 `CommandRouterPort`（向 sibling/child inbox 提 Command）；实现落 **L6 surfaces**（持 `RunRegistry`，组合根注入），**kernel 只 import Port**（C1/S7）；capability token 防伪句柄（借 hermes HMAC，见 §7 备选） | L0/L2/L6 | T0/T3 | 分层守卫 `check_layering_ast` + 冷导入 | `feat(ports): SubagentSpawner/CommandRouter ports (L6 impl, L2 injects)` |
| **T6** | `capabilities/subagent/`（新建，替换 stub）：orchestrator 消费策略 `ProposeSpawn` 意图 → **fan-out admission gate**（`max_parallel_children` reservation，wuu `spawn_slot` 式）→ 提 `SpawnSubagent` Command 到父 inbox（**不直接建 run/写状态**，C2/C16）；`max_tree_depth` 判定 | L3 | T0/T3/T5/T7 | 集成（gate 拒超发）+ 单测 | `feat(capabilities): subagent orchestrator + fan-out admission gate (P8 gate per ADR-0039)` |
| **T7** | 权限投影 `project_parent_permission(parent_ctx)->child_ctx`（`mode` 保守默认、`rules⊆父`、`denylist=父∪{新}`、floor 同 OS）；越权放宽 fail-closed 抛错 | L2/L0 | T0 | 单元（DoD④）：子 denylist ⊇ 父、rules ⊆ 父、父 full_auto 不降子 ask | `feat(kernel): child PermissionCtx projection (subset-of-parent, fail-closed)` |
| **T8** | 取消传播：reduce 是纯函数、**不 import surfaces**；改为 **loop 在 reduce `Cancel` 得新 Run 后读其 `task_tree`**、经注入的 `CommandRouterPort`（kernel 只 import Port，实现在 L6 持 RunRegistry）向每个未终态 `kind=subagent` 子 inbox 提 `Cancel(owner)`；父 cancelled 后 `RunController.close()`、迟到 `ReportChildTerminal` 得 REJECTED_TERMINAL receipt（不复活已取消父） | L2/L0/L6 | T0/T3/T5/T6 | 集成（DoD⑤）+ 竞态样例（子终态与父 freeze 竞态不重启已取消父） | `feat(kernel): subtree freeze on parent Cancel via Cancel(owner) Commands` |
| **T9** | `--resume` 集成：`list_unfinished_runs()` 枚举父+子；各自 `rebuild_run`；父 resume 后扫 `assigned_run_id` 指终态未 ack 者幂等提 `ReportChildTerminal` | L1/L2/L6 | T3/T5 | 集成（kill 父→`--resume`，DoD⑥⑦） | `feat(resume): multi-run resume + orphan child terminal re-claim` |
| **T10** | 守卫扩面：`check_replay_determinism._canonical` 加 **task_tree 骨架**（node id/status/parent_id/deps/assigned_run_id）+ 新 fixture（spawn-and-report / multi-child-concurrent-report）；`check_protocol_schema --self-test` 加 `peer_*` valid+bad fixture；`check_projection_whitelist` 确认 `peer_*` 键不入 `_DATA_KEYS`；`check_layering_ast` FORBIDDEN_IMPORTS 加 `capabilities/subagent ✗ surfaces/providers/store` | scripts/L* | T1–T9 | 各脚本 `--self-test` 判红 + `check` 判绿 | `test(gates): extend replay/protocol/projection/layering guards for P8` |
| **T11** | 集成：两真 run 协作完成一任务（DoD①②，脚本化 provider，2 并发 SSE 订阅者验 seq 恰一行） | tests | T1–T10 | pytest integration | `test(integration): two-run collaboration DoD (parent observes child terminal, no bypass write)` |
| **T12** | 判红：环/悬空/自环 reduce 拒 + 错误事件 + 不崩（DoD③） | tests | T3/T4 | pytest | `test(state): malformed DAG rejected in reduce without crash (red-first)` |
| **T13** | 判红：预算耗尽/超 fan-out 宽度终止顺序（E2：取消>安全告警>超时>预算）+ 失控防护（DoD + §7） | tests | T6/T8 | pytest | `test(kernel): fan-out budget + E2 terminal priority propagation` |
| **T14** | 文档收尾：`design/01` §3/§12/§13 与实现一致、`ROADMAP §1.5` P8 备注、`CHANGELOG`、`capabilities/subagent/README.md` 去 stub | docs | 全部 | 文档自检 | `docs: record P8 outcome into design/01, ROADMAP §1.5, subagent README` |

> **开工次序**：T0 → (T1→T2) → T4 → T3 → T7 → T5 → T6 → T8 → T9 → T10 → {T11,T12,T13} → T14。每条 T 内部按 TDD：**先写判红用例跑红 → 最小实现转绿 → 过冷导入/守卫 → 提交**（AGENTS §4/§5、细粒度原子提交）。

### 4.1 评审细化（对抗评审 Major：spawn 层界与时序，实现者不得再自行决策）

> 依赖方向铁律（C1）：**L2 `kernel/loop.py` 绝不 import L3 `capabilities/subagent`**。策略 `ProposeSpawn` 意图由 loop 交**注入的抽象端口** `SubagentSpawnerPort`（定义在 `contracts/ports.py`，L0）处置；实现体在 L3/L6，组合根（`__main__.py`）接线。`check_layering_ast` 守。
>
> **spawn 时序（reduce 纯函数、不建 run）**——对齐 `WriteMemory` 的"reduce 发事件、消费点做 IO"：
> 1. 端口实现先**预生成 `child_run_id`** + 用 T7 投影出 `child_permission_ctx`（子⊆父）+ 组子 Run 骨架（budget/初始 root node）；fan-out gate（`max_parallel_children` reservation，wuu `spawn_slot`）在此处判定、超发直接拒、**不提交 Command**。
> 2. 端口向**父 inbox** 提 `SpawnSubagent{child_run_id, node_id, spawn_key, child_ctx}`（经 `CommandRouterPort`，非直改父状态，C16）。
> 3. 父 loop 唯一消费者 `reduce(parent_run, SpawnSubagent)`：命中 `spawn_key` 幂等（重复→no-op/`WARNING`）；成功则置 `node.assigned_run_id=child_run_id`+`node.status=active`+发 `peer_started`（占父 seq）。**reduce 不创建子 run**。
> 4. **仅当 reduce 受理成功后**，端口才真正 `register` 子 RunController 并把子 loop 作为 asyncio 任务起跑（side-effect at consumption）。replay/重投同 `spawn_key` → 第 3 步 reduce 判重 → 不产生第二个子。
> 5. 子到终态 → 子 loop 经端口向**父 inbox** 提 `ReportChildTerminal`（携 `result_ref` 指针、非正文）→ 父 reduce 回填 node + 发 `peer_ended`。父 cancelled 后 `ReportChildTerminal` 得 `REJECTED_TERMINAL`（不复活）。
>
> 被否：把建 run/注册塞进 reduce（破纯函数 + 违 C1 让 L1 够到 L6）；先建子再提 Command（reduce 若拒则留孤儿子，破坏 exactly-once）。

---

## 5. 契约与红线自检（逐条 C1–C20，以文件现场数为准 = **20 条**）

| 红线 | 合规判定 | 说明 / 例外（需 ADR） |
|---|---|---|
| **C1** 分层依赖方向 | 合规 | 编排机制 L3、调度 L2、状态字段 L1/contracts、事件 L0、注册 L6；`check_layering_ast` 扩 FORBIDDEN_IMPORTS（T10） |
| **C2** 单写者+不可变视图 | 合规（核心） | **跨 run 不得互写**：父观察子只经 `ReportChildTerminal` Command→父 reduce；子只被自己 loop 写。`reduce` 产新 State 不原地改（既有） |
| **C3** 视图 vs 快照 | 合规 | `PolicyView.task_tree` 只读投影；无每轮全量深拷 |
| **C4** Store 读写过接口 | 合规 | 策略/编排无裸 StorePort/句柄；`SubagentSpawnerPort` 抽象经注入（T5） |
| **C5** Command/Event 分离 | 合规 | 子终态是 Event、回灌父是 Command；Event 不反哺状态 |
| **C6** 事件内外分层+版本 | 合规 | `peer_*` additive、未知 type 静默忽略（错误类除外）；**`v` 不 bump**（ADR-0042） |
| **C7** 终止权在 Harness（走命令） | 合规 | 取消经 `Cancel(owner)` Command 传播、**不 out-of-band 硬杀**；子 reduce 回填自身 open tool_call |
| **C8** 工具执行边界 | 合规 | spawn 是内核机制、非工具直改状态；权限/denylist/floor 照走 |
| **C9** 权限三态一等+沙箱可插拔 | 合规 | 子 `ask`→`awaiting_approval`+HITL 事件；后端不变 |
| **C10** 故障隔离 | 合规 | **子 run panic 崩不到父**：子异常经 ADR-0028 归一子自身 `run_failed`；父只观察 `peer_ended(terminal=failed)`，不共享异常栈 |
| **C11** 状态模型谨慎演进 | 合规（有例外走 ADR） | **不加** `edge_kind/path/depth/resumable`、不启用 `WAITING_CHILDREN`（§2-7/8）；启用 DAG 校验属"字段已存、接上消费者"，非新增接缝 → ADR-0037 |
| **C12** 远程/分布式预留非现在 | 合规 | v1 同进程 asyncio 多 run；跨进程/机 exactly-once/lease = P9 天花板，**不越界**（§2-10） |
| **C13** 存储/终态两铁律 | 合规 | 每 run 恰一终态（first-writer-wins，既有 per-run `_closed` 集）；只存内部事件、外部投影不入库 |
| **C14** 结构性边界靠机器守 | 合规 | kernel 不 import surfaces；`SubagentSpawnerPort` 抽象在 contracts、实现在 L6；每条守卫 `--self-test`+fail-on-empty |
| **C15** 外部契约单一真源+守卫可信 | 合规 | **三处 lockstep**：contracts ⟂ `protocol/event.schema.json` `$defs` ⟂ TS codegen（`check_protocol_schema`）；新增类型必同步 fixture |
| **C16** Command Inbox 唯一外部写入口 | 合规 | surfaces 只 `RunRegistry.submit(run_id,…)`；`SpawnSubagent/ReportChildTerminal/Cancel` 全走各 run inbox |
| **C17** PermissionCtx/floor 优先于 mode | 合规 | 子 `denylist` 权威只扩大、floor 同 OS 不放宽；父 full_auto **不**降子 ask（ADR-0040） |
| **C18** ToolCall 生命周期+载荷有界 | 合规 | 未闭合 `tool_use` 全路径回填（reduce `Cancel/FinalizeRun`，既有）；`peer_*` 正文走 artifact 指针不内联 |
| **C19** 回发前配对+provider 故障不崩 | 合规 | 关卡仍在唯一 `provider.stream` 调用点；子 run 各自守；**不借 P8 放宽执行串行**（工具 gate 另议 ADR-0039） |
| **C20** 观测面不作第二载体 | 合规 | `node_updated`/`peer_*` 正文不进 `projection._DATA_KEYS`；委派正文不进事件流/日志；`check_projection_whitelist` 守 |

**事件协议"只增不破信封/关联键/终止序"核验点**（design/02 §0/§6/§7）：
- 信封 `{v,seq,run_id,turn?,ts,type,data}` **不动**；关联键 `run_id/turn/tool_call_id/card_id/item_id` **不改名**（`peer_*` 用 `parent_run_id/child_run_id` 作 data 字段、不新立关联键）。
- **终止序不破**：`run_cancelled` 先于 `run_completed`、一轮恰一终态——`peer_*` 非终态事件，不改 run 终止序。
- 类型计数 20→22 **不 bump `v`**（additive；`check_protocol_schema` 断言 enum==$defs==branches==contracts 白名单键集，T2/T10）。

**跨平台/宿主差异**：`--resume` 多 run 枚举依赖 SQLite `BEGIN IMMEDIATE`（单机单写者）；**不假设** `contextvars` 过边界（pitfalls #3）——子 run 关联键显式随记录传，若 P9+ 跨进程 spawn 则 stderr 注入 `run_id`。

---

## 6. 测试与回归

**单元**
- reduce：`SpawnSubagent` 幂等（同键两次只一个子）、`ReportChildTerminal` 回填、`ProposePlanUpdate` 接 task_tree；非法 Command → 拒 + warning、不崩。
- DAG 校验：环 A→B→A、悬空 `deps=[ghost]`、自环 A→A、重复 node_id → 各一条判红，断言 `task_tree` 不变 + 发错误事件。
- 权限投影：子 denylist ⊇ 父、rules ⊆ 父、mode 不放宽、floor 同 OS（DoD④）。
- fan-out gate：超 `max_parallel_children` 被拒（reservation 不超发）；超 `max_tree_depth` 被拒。

**集成**
- `test_p8_two_run_collaboration`：父 spawn 子→子 `run_completed`→`ReportChildTerminal`→父 `peer_ended`；断言 `child_run_id≠parent_run_id`、父账本无旁路写。
- `test_p8_parent_cancel_subtree`：父中途 `Cancel(user)`→每 live 子 `run_cancelled(cancel_reason=owner)`、子 tool_ledger 配对完整、partial 保留（子 checkpoint 有快照）。
- `test_p8_child_fault_isolation`：子 provider 崩→子 `run_failed`、父继续、`peer_ended(terminal=failed)`。
- `test_p8_out_of_band_projection`（承 pitfalls #5）：开 2 并发 `/events` 订阅者跑父+子，主干日志每 seq 恰一行、`peer_*` 不双投。
- `test_p8_cross_run_no_bypass`（源码级 fail-on-empty）：断言全仓无 `child_run.<field> =` 式跨 run 直写、跨 run 只经 `submit(...)`。

**守卫扩面**（`--self-test` 必能判红 + `check` 判绿 + fail-on-empty）
- `check_protocol_schema --check/--self-test`：`peer_*` 入 enum/$defs/branches + `_valid_fixtures` 两条 valid + 超 maxLength/未知字段 bad。
- `check_replay_determinism`：**`_canonical` 加 task_tree 骨架**（否则 P8 状态漂移全绿，是最危险的假绿）；新 fixture `spawn-and-report`（split 在 `peer_started` 后、`peer_ended` 前）+ `multi-child-concurrent-report`（**交换子 Command 提交顺序、断言父 canonical 一致** = DoD⑦可证伪判据）。
- `check_projection_whitelist`：`peer_*`/委派正文键 ⊄ `_DATA_KEYS`、∩ DENY_KEYS=∅。
- `check_layering_ast` / `lint-imports`：`capabilities/subagent` ✗ `surfaces/providers/store`；kernel ✗ surfaces。
- `check_thin_client`：桌面若加多 agent 视图，只消费事件、零业务下沉。
- 冷导入 `uv run python -c "import questor.capabilities.subagent"`。

**跨平台钉宿**：`--resume`/fan-out 测试用脚本化 provider + `tmp_path` SQLite，不依赖真机窗口/真 LLM；若涉 stdout 断言，按既有 `PYTHONIOENCODING=cp1252` 那样在测试内钉住宿主差异（承 `main` 上 `d730938` ASCII 化教训），不靠"恰好有台机器"。

---

## 7. 风险 & 备选

| 风险 | 触发条件 | 缓解 | 被否备选 |
|---|---|---|---|
| **I6 漂移复活**：文档仍写"v2/DAG 后置"，代码在 P8 做了校验 | 未先落 ADR-0037 就动 reduce | T0 先修订 I6 + §3/§12/§13，就地记账；对抗评审①专查 | 边写边猜、把校验藏进 T3 不记 ADR → 否（正是要消灭的漂移） |
| **重演隐债**："字段存在≠gate 存在"（ADR-0029 的坑） | T3/T4 只加字段不接消费者 | 判据绑定：T4 必须真消费 `deps`、T3 必须真消费 `assigned_run_id`；`check_replay_determinism` 的 task_tree 断言兜 | 只补 `WAITING_CHILDREN` 语义不接 fan-in → 否（死字段） |
| **fan-out 失控**（spawn 风暴烧预算） | 策略递归/大量提议 | `max_parallel_children`(4)+`max_tree_depth`(1)+reservation 防超发+E2 终止优先级 | 无上限 fan-out → 否；跨进程信号量 → 否（C12/P9） |
| **权限放大**（子比父宽） | 投影函数漏 `denylist` 并集 | ADR-0040 fail-closed + DoD④ 判红 + hermes 子集判据 | 继承父 mode → 否（full_auto 传下去即放大） |
| **载荷外泄**（正文进事件/日志） | 图省事塞 `message`/`body` | `peer_ended` 只带 `result_ref` 指针；`check_projection_whitelist` + 字段级 `additionalProperties:false` | 全文进 event → 否（C18/C20，ADR-0019 已否） |
| **回放假绿**（task_tree 漂移无人查） | `_canonical` 不含 task_tree | T10 扩 `_canonical` + DoD⑦ 顺序无关 fixture | 不扩 → 否（最危险的静默错） |
| **取消竞态重启已取消父**（子恰在 freeze 时终态） | 子终态与父 Cancel 交错 | wuu `tree_freeze` 的"gate 嵌套结果唤醒"语义 v1 化：父 cancelled 后 inbox 关闭、迟到 `ReportChildTerminal` 得 REJECTED_TERMINAL receipt、不复活 | 允许迟到唤醒父 → 否 |
| **跨进程 exactly-once 误承诺** | 把 P9 的 claim 账本塞 P8 | §2-1/§6 显式 UNVERIFIED；v1=at-least-once+去重键，诚实标注 | 现在就上 DB lease/claim → 否（C12/ADR-0021 后置 P9） |

---

## 8. 收尾（活文档，AGENTS §5.5）+ 偏差回填占位

- [ ] **偏差回填**（实现收尾时写"实际 vs 计划"）：本节追加"P8 落地备注"，与 `docs/plan/07 §8` 同风格；Reality-wins（VISION §0.4）。
- [ ] **UNVERIFIED 诚实边界**（定死，不冒充）：真 LLM / 真远程 MCP server / 真开窗口驱动多 agent / **跨进程 exactly-once**（后置 P9）——逐条列。
- [ ] `ADR-0037`：I6 修订 + DAG 启用范围（`design/01` 就地改 + 本 ADR 转正）。
- [ ] `ADR-0038`：子 agent 本体 + 取消传播 + at-least-once + 载荷边界。
- [ ] `ADR-0039`：并行 gate 归口再决（更新 `ADR-0029` 的"暂定归口"悬置、改 `ROADMAP §1.5/§2.5` 口径）。
- [ ] `ADR-0040`：子权限继承收缩。
- [ ] `ADR-0041`：fan-out 预算与失控终止。
- [ ] `ADR-0042`：`peer_started/peer_ended` additive 定形。
- [ ] `design/01-state-model.md`：§3/§10/§12/§13（I6、TaskNode 消费者、subagent→独立 Run 落点）就地修订，去"v1 不使用/占位"陈旧口径。
- [ ] `design/02-event-protocol.md`：§3 表加 `peer_*`、§7 由"预留名"转"已定义"、§10 关联投递幂等。
- [ ] `ROADMAP.md §1`（P8 DoD 落定）+ `§1.5`（P8 备注）；**序列仍 P8→P9→P10**（ADR-0036）。
- [ ] `CHANGELOG.md [Unreleased]` 追加 P8 条目。
- [ ] `capabilities/subagent/README.md`：去 "empty until P8" stub、写实际职责与层。
- [ ] `docs/pitfalls.md`：若实现期新增跨进程/事件形状类陷阱，按格式补条目（普通 bug 走 Issue，不入此）。

**开工前置门（本计划定稿后，实现开始前）**：
1. 对抗式评审两路并行——**①契约完备性与不变式破坏**（I6/seq/终态唯一/lockstep/回放）；**②范围漂移与安全边界/权限继承/载荷外泄**（§2/§5/§7）。
2. Blocker/Major 全关 → 按 ADR-0012 建 worktree 分支（`feat/p8-multi-agent-dag`）。
3. 实现严格按 **T0 先 ADR**、TDD 先红后绿、细粒度原子提交；**每次 commit/push 前逐次征求许可**（AGENTS §6，绝不擅自提交/推送）。

---

## 待拍板清单（每条：选项 · 推荐 + 代价 · 落成 ADR）

> 以下 6 条是本阶段"信息不足以单方面定夺"的真决策。我给出推荐，但**需要你拍板**；未拍板前，§3/§4 按推荐态写死、标此为待确认。

**D-1 子 agent 本体：独立 Run（推荐）vs 同 run 节点扇出？**
- 推荐：**独立 Run**（同进程 asyncio，经 `assigned_run_id` 关联，跨 run 只经 Command）。代价：多 run 交织使 `--resume`/投影更复杂，需扩 `check_replay_determinism`。落 **ADR-0038**。
- 否：同 run 节点扇出——会把"子 agent 独立终止/独立权限上下文/独立账本"挤进单 run，违 C2 per-run 单写者与 C7 终止粒度。

**D-2 P8 启用哪一层 DAG？（I6 冲突裁决）**
- 选项：(a) **只做 reduce 侧依赖校验 + 读侧就绪判定（推荐）**；(b) 连拓扑调度器一起落。
- 推荐 (a)。(b) 代价：内核主动 fan-in/fan-out 破坏单步 `PolicyPort`（design/05）、逼出 `edge_kind/path/depth`+`WAITING_CHILDREN`（C11 过早焊死），DoD"两 agent 协作"并不需要。落 **ADR-0037**（+ 就地改 I6）。

**D-3 并行 gate（ADR-0029 悬置）：P8 接住 or 再推后一次？**
- 选项：(a) **P8 只落子代理 fan-out gate、工具 reader/writer gate 再推后一次（推荐，落 ADR-0039）**；(b) P8 同时接工具 gate；(c) 另立独立并行化 Phase。
- 推荐 (a)。fan-out 是 run 级并发、与工具级并发正交；(b) 把两条高危改动叠进一个 blast radius（正是 ADR-0029 反对的）。代价：工具 gate 的账要多记一次（ADR-0039 显式点名，绝不重演"注释说 P#、其实没人做"）。

**D-4 子权限继承默认档位？**
- 选项：(a) **子 `mode` 强制 `default`、不继承父 mode，父须显式逐子提权（推荐，最保守 fail-closed，落 ADR-0040）**；(b) 继承父 mode 但 denylist/floor 只严不宽。
- 推荐 (a)：把"便利"与"隔离"分开，避免父 `full_auto` 传染成子无围栏执行。代价：父 `full_auto` 下子仍频繁 `ask`，需显式配置才顺滑——这是刻意的安全默认。

**D-5 fan-out 默认上限值？**
- 选项：`max_parallel_children` 默认 {2 / **4（推荐）** / 8}；`max_tree_depth` 默认 **1（推荐，父不直接生孙）**。
- 推荐 4 + 1：参照 hermes `_EXECUTOR max_workers=8` 取保守半，且深度 1 覆盖 ROADMAP DoD"两 agent 协作"。代价：更深编排（agent 树）需你显式放开深度并补 ADR（递归取消/预算更复杂）。

**D-6 `peer_*` 事件是否进带外日志投影？**
- 选项：(a) **只进事件协议、不进 `projection._DATA_KEYS`（推荐，最贴 C20，落 ADR-0042）**；(b) 把 `child_run_id`（关联键、非载荷）纳入日志白名单便于排障。
- 推荐先 (a)，P10 observability 刀 3 再评估 (b)。代价：(a) 下排障要看事件流而非日志。

---

## 9. 落地偏差回填（实现收尾，AGENTS §5.5 Reality-wins）

- **机制细化（不改契约/不变式）**：计划的"ProposeSpawn 意图 + loop 消费点建子"改为 **`delegate` 工具走既有工具生命周期 + "委派即 await 子终态"**。原因：① `design/00` 本就把子 agent 编排归 L3 能力，工具路径复用权限/沙箱/超时/配对，改动面最小（AGENTS §2/§3）；② 若父 loop 阻塞在"等子"上就不能同时 drain 自己 inbox 去 `materialize_child`（会死锁），故子由端口**直接起跑**、`SpawnSubagent`/`ReportChildTerminal` 仍经父 inbox 做记账+发 peer 事件（跨 run 只经 Command 不变，C2/C16）。loop `_consume_commands` 的 materialize 钩子保留且幂等，用于崩溃/回放重实体化。
- **`orchestrator`/`parallel_safe`/`barrier` 口径**：`orchestrator` 现为"会 spawn 子 run"的标记，真正的 fan-out 上限由 `SubagentSpawnerPort` admission gate 强制（非派发读位改并发）——刻意不重演 ADR-0029 的"字段存在≠gate 存在"。工具 reader/writer gate 经 ADR-0039 显式再推后至 P10/独立 Phase。
- **已机器验证 vs UNVERIFIED（定死不冒充）**：DoD①②③④⑤⑦ + spawn 幂等/快照 round-trip 全绿（`tests/{unit,integration}/test_p8_*` + `test_p8_two_run_collaboration` 两真 run 端到端）。**UNVERIFIED**：真 LLM/真开窗口驱动多 agent；跨进程 exactly-once（claim/delivery_state 账本，ADR-0021/0038 归 P9）；工具级真并发 gate。
- **守卫现状**：`check_protocol_schema` 22 类型 lockstep、`check_replay_determinism` 4 fixture（含 task_tree + 子顺序无关）、`check_projection_whitelist`/`check_layering_ast`(110 文件 0 违规) 全绿；全量 730 passed。
- **收尾**：ADR-0037~0042 已落册、design/01 I6+§3/§13 与 design/02 §3/§7 已就地修订、ROADMAP §1/§1.5、CHANGELOG、subagent README 去 stub 均已同步。未合 main（PR-only，push/merge 待逐次授权）。
