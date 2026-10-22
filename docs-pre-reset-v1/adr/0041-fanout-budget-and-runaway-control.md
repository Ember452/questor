# ADR-0041: fan-out 预算与失控终止（宽度/深度上限 + usage 归 per-run + E2 优先级）

- 状态：✅（2026-10-18，P8 开工前置门；实现见 `docs/plan/08-p8-multi-agent-dag.md` T6/T13）
- 背景：子 agent fan-out 引入新失控面——spawn 风暴（递归/大量提议把 CPU/token/wall-clock 打满）。`contracts/state_schema.py::Budget` 已有 `max_turns/max_tokens/deadline_seconds/repeat_tool_limit/…`（per-run），但无"编排级"宽度/深度约束。须定：谁限、限多少、超限谁先终止、用量如何归因。peer：wuu `spawn_slot.go`（`maxParallel` control-local reservation）、hermes `_EXECUTOR max_workers=8`（有界 worker 池）。
- 决策：
  - **新增可选预算字段**（additive，只增不改，C6/C11）：`max_parallel_children`（fan-out 宽度上限，默认 **4**）、`max_tree_depth`（编排树深度上限，默认 **1**——父不直接生孙；放开需显式配置并补 ADR，因递归取消/预算更复杂）。二者放 `Budget` 或新建 `FanoutBudget`（实现者择一，语义一致即可）。默认 `None/0` 语义 = 不允许 fan-out（保守默认，与 `TaskKind.SUBAGENT` 占位期一致）。
  - **宽度用 reservation 强制**（wuu `spawn_slot` 形状，落 L3 端口，见 [ADR-0039](./0039-parallel-gate-attribution-recut.md)）：spawn 前"登记预留→判 `running+pending < max`→放行/拒绝"，防 TOCTOU 超发；拒绝即**不提交 `SpawnSubagent`**、发 `warning`/有界 error（不崩，C10）。
  - **usage 归 per-run，不汇聚父**：`usage_delta` 事件仍属各 run 的账（C13 per-run 权威计量、run 隔离）。父 `budget` **不含**子消耗。若产品要"父视角总花费"→ P10 observability 基于全局 `gseq` watermark 聚合，**不改内核、不新增第二真相**。
  - **超限/失控的终止优先级**（对齐 `design/02 §9` E2 与 `CancelReason`：`contracts/state_schema.py:35-43`）：**用户取消 > 安全告警 > 超时 > 预算耗尽**，reduce 串行 first-writer-wins、一轮恰一终态（C13）。
    - 父 `budget`（turns/tokens/deadline）耗尽 → 父落 `run_cancelled(cancel_reason=budget_exhausted)` + **递归 `Cancel(owner)` 未终态子树**（经 `CommandRouterPort`，不硬杀，C7）。
    - 子 `budget` 耗尽 → 子自己 `run_cancelled(budget_exhausted)` + 回填自身 open `tool_use`；父观察 `peer_ended(terminal=cancelled)`，是否重 spawn 交策略（单步提议）。
  - **护栏沿用既有**：`repeat_tool_limit`/`max_consecutive_continuations` per-run 生效；编排层再加"同 `(parent,objective)` 的 spawn 频率"轻量护栏（可选，判据=防策略死循环刷 spawn，参照 `design/04 §6`）。
- 后果：
  - 正面：fan-out 有确定上界、失控可终止且终止序唯一可审计；用量口径诚实（不谎称父已含子消耗）；默认保守（不显式放开即不 fan-out/不生孙）。
  - 代价/需持续守：深度默认 1 使"agent 树"受限——真多跳编排须显式放开 + 新 ADR；`usage` 聚合不在内核，跨 run 总花费归 P10（本 ADR 点名，避免误以为已做）。
- 备选（被否）：
  1. **无上限 fan-out**：spawn 风暴拖垮内存/CPU/预算，违"有界"总原则 → 否。
  2. **usage 汇聚到父 run 账**：破 per-run 单写者权威 + 第二真相；且跨机时对不齐 → 否，聚合归 P10 观测面。
  3. **跨进程 `maxParallel` 信号量**：v1 同进程不需要，跨进程是 C12/天花板（ADR-0038）→ 否。
- 关联：HARD-CONSTRAINTS C7/C10/C13；ADR-0029/0038/0039；`contracts/state_schema.py::Budget`/`CancelReason`；`design/02 §9`(E2)、`design/04 §3/§6`；peer：wuu `spawn_slot.go`、hermes `subagent_lifecycle.py:160`（MIT）。
