# ADR-0037: I6 语义修订 + P8 的 DAG 启用范围（校验落 P8、拓扑调度器后置）

- 状态：✅（2026-10-18，P8 开工前置门；实现见 `docs/plan/08-p8-multi-agent-dag.md` T3/T4）
- 背景：`docs/design/01-state-model.md` I6（`:181`）与 [ADR-0008](./0008-evolution-strategy.md)（`:8`）都把 DAG 写作"仅预留、v2 再启用、理由=降 reduce/调度/恢复复杂度"；但 `docs/ROADMAP.md §1` 的 P8 DoD 却明写"DAG reduce 校验通过"。二者正面冲突：若 P8 什么都不做就是路线图违约，若 P8 把整套 DAG 调度器都落就是违 I6 且过早焊死。`contracts/state_schema.py:199` 的 `deps` 字段注释"v1 仅做前置读校验，不做拓扑调度"也停在纸面——**字段存在但 reduce 无消费者**，正是 ADR-0029 反复警告的"注释说 P#、其实没人做"的隐债形状。
- 决策：
  - **拆开 ADR-0008 混在一起的三件事**——① reduce 依赖校验、② 拓扑调度器（内核主动 fan-out/fan-in 派发）、③ 跨 fan-in 的断点恢复。P8 **只启用 ①**，②③ 后置。
  - **① 落在 reduce 内部（I1/ADR-0004）**：`_validate_task_dag` 强制"无环 / 无悬空 `deps` / 无自环 / `node_id` 唯一 / 节点终态唯一"；非法 `UpdateTaskTree`/`SpawnSubagent` 命令被 reduce **拒 + 发 error/warning 事件、不崩、不改 `task_tree`**（判据可在 `check_replay_determinism` 非法-DAG fixture 证伪）。
  - **读侧就绪判定**：策略可从 `PolicyView.task_tree` 读 `deps` 判断节点能否激活；**"分发/调度"仍由策略每轮 `ProposeAction` 单步提议 + reduce 校验**——内核不主动按拓扑派发（不破 `design/05` 的单步 `PolicyPort` 接口）。
  - **就地把 I6 改到与新现实一致**（不留"文档说 v2、代码在 P8 做了"的漂移）：I6 措辞改为"**v1 森林拓扑 + reduce 强制依赖校验（无环/悬空/自环/终态唯一）+ 读侧就绪判定；拓扑调度器与 `edge_kind/path/depth` 后置**"。同步修订 `design/01` §3/§10/§12/§13 与 `design/02 §7` 的"预留"口径。
  - **不动状态字段接缝**：P8 **不新增** `TaskNode.edge_kind/path/depth/resumable`、**不启用** `TaskStatus.WAITING_CHILDREN`（fan-in 属②调度器）。`deps`/`assigned_run_id` 早已在契约里，P8 是"接上消费者"非"新增接缝"。故 **checkpoint 快照 schema 保持 v3、`store_schema_version` 的 fail-closed 语义绝不放松**（ADR-0024/0020）。
- 后果：
  - 正面：ROADMAP "DAG reduce 校验通过" 的字面 DoD 达成；`deps` 从死字段变活；reduce 仍是唯一写者、仍是纯状态机；快照协议零变更（不触发历史迁移）。
  - 代价/需持续守：②③ 仍在——真正需要拓扑调度（内核主动并发派发 + fan-in 汇聚 + 跨 fan-in 恢复）时要另记 ADR 并届时才 bump 快照版本；`WAITING_CHILDREN` 继续占位、注释须诚实标注"启用随②"。
  - 取代关系：本 ADR 修订 [ADR-0008](./0008-evolution-strategy.md) 的"①②③ 一起 v2 启用"表述——**不回改 ADR-0008 正文**，在此登记"①提前到 P8、②③仍后置"。属 ROADMAP §5 允许的阶段内功能移动。
- 备选（被否）：
  1. **P8 连拓扑调度器一起落**：破坏单步 `PolicyPort`（design/05）、逼出 `edge_kind/path/depth`+`WAITING_CHILDREN`（C11 过早焊死）、DoD"两 agent 协作"并不需要 → 否。
  2. **P8 什么都不做（守原 I6）**：违 ROADMAP DoD，且 `deps` 继续是"字段存在≠gate 存在"的隐债（ADR-0029 之坑）→ 否。
  3. **只在 loop/策略层校验、不进 reduce**：不变式必须"在 reduce 内部强制"（I1/ADR-0004），否则 resume/回放绕过校验 → 否。
- 关联：`docs/design/01-state-model.md` §3/§10/§12(I1/I6)/§13、`docs/ROADMAP.md §1`(P8 DoD)/§5；[ADR-0004](./0004-state-mutation-model.md)（I1 在 reduce）、[ADR-0008](./0008-evolution-strategy.md)（本 ADR 细化其 DAG 条款）、[ADR-0024](./0024-memory-contract-evolution.md)（快照 v3 fail-closed）、HARD-CONSTRAINTS C11/C13。
