# ADR-0013: Run 级 Command Inbox 是外部写意图的唯一入口

- 状态：✅（2026-10-15）
- 背景：P2 的 `/approve`、`/permissions` 和后续 IM、桌面、远程策略都要向一个**已经运行中的 run**提交 Command。当前 surfaces 直接持有并启动 loop，没有可串行消费 Command 的入口；若 surfaces 直接调用 `reduce()`，会与 loop 持有的当前 `Run` 实例竞争，破坏 HARD-CONSTRAINTS C2/C5 的单写者模型。
- 决策：
  - Kernel 为每个 active run 创建一个 `RunController`，其中持有有界、按 FIFO 消费的 `CommandInbox`。
  - L6 surfaces 只实现 `CommandInboxPort.submit(command, source, idempotency_key)`，不得直接调用 `reduce`、Store、权限引擎或修改 Domain_State。
  - loop 在每个安全点消费 Command；进入审批等待时，同一 inbox 同时消费 `ResolveApproval`、`ExpireApproval`、`Cancel`，确保审批与取消只有一个串行裁决点。
  - 每个 Command 携带来源与幂等键；重复 Command 返回 receipt 且不重复产生 durable event。receipt 是 surface 同步返回值，不是第二份持久真相；只有 Command 被 loop 取出并进入 reduce 时才占 run 的 durable seq。队满时 surfaces 得到明确拒绝，绝不静默丢弃。
  - 终态后 inbox 关闭；迟到 Command 被拒绝并返回可观测 receipt，不能复活 run。
- 后果：审批、取消、权限模式修改和未来远程 Command 都复用同一接缝；代价是 surfaces 必须改为异步提交并处理 receipt/backpressure。该成本远小于把 Command 分发散落进 CLI、HTTP、Tauri 后返工。
- 备选（被否）：
  1. surfaces 直接调用 `reduce()`：制造第二写者，状态可撕裂 → 否。
  2. 审批继续用阻塞回调：能演示 CLI，但无 durable request、无法超时/取消/重放，P7/P9 必重写 → 否。
  3. 每个 surface 各维护一套审批等待器：幂等、seq、terminal uniqueness 口径漂移 → 否。
- 关联：HARD-CONSTRAINTS C2/C5/C14；[`../design/01-state-model.md`](../design/01-state-model.md) §7、[`../design/02-event-protocol.md`](../design/02-event-protocol.md) §5、ADR-0016。
