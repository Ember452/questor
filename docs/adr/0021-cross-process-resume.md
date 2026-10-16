# ADR-0021: 跨进程续跑协议（resume = 最近快照 + 重放耐久尾 + 回填修复 + 幂等 re-dispatch）

- 状态：✅（2026-10-16）
- 背景：P2 的 `kernel/recovery.py::resume_run` 只读**最近一个 checkpoint**、闭过期审批后返回 `Run`，且**零生产调用者**——没有"重启即续跑"的驱动入口，也没有把快照之后已落库的耐久事件重放进来。ROADMAP P3 判据"kill 进程后重启能续跑/回放、且不重复副作用"要求两件事同时成立：① 从持久态重建权威 `Domain_State`；② 把恢复出的 run 交回唯一 `DefaultTurnLoop` 继续驱动到唯一终态，且**已完成的工具不得重跑**（写/exec 是不可逆副作用）。R03（hermes `async_delegations.delivery_state`、wuu `claimAgentResultDelivery`）给的是跨进程 exactly-once 的重方案，本项目 v1 单机用更轻的判据。
- 决策：
  - `rebuild_run(store, run_id)`：`latest_checkpoint` → `from_snapshot` → **重放 `seq > cp.seq` 的耐久事件**把 head 游标/派生投影对齐到崩溃前的真实进度（写门保证快照点自身成对，尾事件均已在 log） → 扫 `pending_tool_calls` 经 `reduce` 回填未闭合调用（读时 repair）→ `_expire_due_approvals`（保留 P2 行为，过期审批经 `ExpireApproval` 显式闭合，不静默蒸发/复活）。
  - `resume_and_drive(loop, controller, run)`：`rebuild_run` 得 `run`；若已终态直接返回（幂等）；否则以 `run` 挂进 `RunController`，交回 `DefaultTurnLoop._drive_controller` 续跑到唯一终态。provider 上下文由恢复出的 `context.items` 重建，保证成对。
  - **幂等 re-dispatch（v1 单机判据）**：仅对账本中仍处 OPEN 状态（pending/validated/awaiting/ready/running 且无 `seq_result`）的调用重新派发；凡已有 `seq_result`/进入终态 status（success/error/denied/cancelled/timed_out）的调用**绝不重跑**。工具侧落盘一次性由 ProcessRunner/工具自身幂等键兜底；完整 claim/delivery_state 账本后置 P9。
  - **resume 不破单写者与 Command Inbox（C2/C16/ADR-0013）**：续跑仍由唯一 loop 消费者经 `RunController` 串行 reduce；surfaces 的 `--resume` / `POST /runs/{id}/resume` 只是**触发 rebuild+drive 的装配动作**与 Command 提交，不得在 surfaces 直接 `reduce`。
  - 稳定幂等键跨 resume 存活：`SubmitMessage` 的 inbox 幂等键用 `submit:{run_id}:{turn}`（非 `submit:{run_id}`），使同一逻辑 turn 重投为 `DUPLICATE` no-op。
- 后果：正面——真 kill→重启能续到正确终态、不重跑副作用、provider 上下文合法；`resume_run` 有生产调用者。代价——OPEN 判定依赖 durable 态准确（写门保证）；跨进程/多副本 exactly-once 仍需 P9 的 lease/claim，本 ADR 只保证单机单写者。
- 备选（被否）：
  1. resume 只取最近快照、不重放尾（=P2 现状）：崩溃在两次快照之间会丢其后已落库的耐久事件进度，违"不丢" → 否。
  2. 现在就上 DB lease + OS 文件锁做跨进程 exactly-once：单机 `BEGIN IMMEDIATE` 已保证单写者，跨机排序是独立硬骨头（C12/天花板），提前做拖累 → 否，后置 P9。
  3. resume 时在 surfaces 直接 reduce 重建：破 C2/C16，制造第二写者 → 否。
  4. 靠"重放会重发事件、消费端去重"实现不重跑副作用：工具副作用不可撤回（写/exec），必须派发侧幂等 → 否。
- 关联：ADR-0004/0005/0011/0013/0016/0020；HARD-CONSTRAINTS C2/C7/C13/C16；[`../design/01-state-model.md`](../design/01-state-model.md) §5/§12(I4/I7)/§13、[`../design/02-event-protocol.md`](../design/02-event-protocol.md) §4/§9(E1/E3)、[`../design/04-turn-loop.md`](../design/04-turn-loop.md) §7。
