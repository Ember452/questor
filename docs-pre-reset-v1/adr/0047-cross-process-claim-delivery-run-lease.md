# ADR-0047: 跨进程 exactly-once claim/delivery_state 账本 + 单机多进程 run lease（接回 ADR-0021/0038 后置）

- 状态：✅（2026-10-18，P9 已实现并验证；实现见 [`../plan-archive/09-p9-openai-plugin-host.md`](../plan-archive/09-p9-openai-plugin-host.md) T8）
- 背景：[`ADR-0021`](./0021-cross-process-resume.md):8/14 把"完整 claim/delivery_state 账本"显式后置 P9；[`ADR-0038`](./0038-subagent-as-independent-run.md):16/21 定"子 agent v1=同进程 asyncio、at-least-once+去重键；完整 claim/delivery_state 持久账本=P9、跨机属 C12 天花板"。P8 已落 `SubagentSpawnerPort`/`ReportChildTerminal`/`peer_ended`（同进程），崩溃对账用现成 `list_unfinished_runs()`/`watermark()`（[`ADR-0022`](./0022-dual-cursor-watermark.md)）。peer-scan：wuu `worker_execution_lease.go`/`delivery.go`（MIT，Go，跨进程 lease 形状）、hermes `gateway/delivery_ledger.py`（MIT，claim-then-deliver-ack）。用户 2026-10-18 拍板"取全局最优、为后续大扩展铺路"。
- 决策：
  1. **`StorePort` 纯增量扩（不破既有签名/信封/关联键，C6）**：
     - 投递账本：`claim_delivery(delivery_id, ...) -> bool`（claim-then-deliver，抢到才投）、`delivery_state(delivery_id) -> state`、`ack_delivery(delivery_id) -> bool`（同 `delivery_id` 二次 ack = no-op）。
     - run 租约：`acquire_lease(run_id, holder_epoch, ttl) -> bool`、`renew_lease(...)`、`release_lease(...)`——靠 SQLite `BEGIN IMMEDIATE` 单写者 + epoch 单调，防两进程双驱同一 run。
  2. **投递视图从事件重放重建、不落第二份真相（C13/C15/design-02 §10）**：claim/delivery_state 是**从 `event_log` 派生的物化视图**（terminal/tool 事件配**稳定投递 id**，承 [`ADR-0011`](./0011-seq-semantics.md)），不是独立持久真相源；崩溃后由 `rebuild_run` + 尾重放重建 claim 状态，绝不允许"投递账本"与"事件流"各写一份分叉真相。
  3. **真接投递路径**：`SubagentOrchestrator` 的 `ReportChildTerminal`/`peer_ended` 投递**必须真接** claim-then-deliver + ack——不是"加方法不接消费者"（承 ADR-0029"字段存在≠gate 存在"教训）；孤儿子终态回灌走 claim 幂等，`list_unfinished_runs` 检出 + 幂等 `ReportChildTerminal`。
  4. **边界（全局最优但不越 C12 天花板）**：接口按"未来跨机 = 换后端（如分布式锁/共识）而非重构调用点"设计；**本 Phase 不实现跨机**——单机多进程（≥2 OS 进程共享一套 SQLite）in-scope，跨主机 = [`HARD-CONSTRAINTS`](../design/HARD-CONSTRAINTS.md) 天花板条/C12，**明确不越界**。
  5. **验证诚实**：**用两个真 OS 子进程共享一套 SQLite 的集成测试端到端验**（本机 Windows 可跑）：两进程对同一 run 争租约只一个赢、同 `delivery_id` 二次 claim/ack 幂等、崩溃重启不留孤儿双回灌 → DoD⑦ 升为**"单机多进程 = 已验证"**；**跨机故障切换 = UNVERIFIED（不冒充）**。
  6. **schema 单一 authority**：新表进 `store_sqlite._SCHEMA` 幂等 `IF NOT EXISTS`、`store_schema_version` 递增、读时未知版本 fail-closed（承 [`ADR-0022`](./0022-dual-cursor-watermark.md)）；写路径继续 `BEGIN IMMEDIATE`（C2）。
- 后果：
  - 正面：还 P8 欠债（ADR-0021/0038 明写"P9"）；单机多进程 exactly-once 有真判据；run-lease 的**生产消费者 = resume 驱动路径**（`CliSurface.resume`/`EventServer.resume` 前取租约、收尾释放、他方持有则 409/None 拒）——独立复核 MA-2 后已真接线（非"原语无人调"）；外部 API lane 每请求起新 run_id、无冲突故不取租约；投递视图从事件派生不新增第二真相。
  - 代价 / 需持续守：多一张投递/租约物化视图需与事件流同步（重建逻辑）；lease TTL/heartbeat 参数经配置（只增不改）；跨机永远另记 ADR；`--self-test` 覆盖投递/租约幂等。
- 备选(被否)：
  1. 现在就上跨机分布式锁/共识 → 否（C12/天花板：跨机排序是独立硬骨头，提前做拖累）。
  2. claim/delivery 独立持久、与事件流各存一份 → 否（第二真相，破 C13/C15）。
  3. 只加 `StorePort` 方法不接 `ReportChildTerminal` 路径 → 否（重演"方法存在≠一致性接入"隐债，承 ADR-0029）。
  4. 继续停在 P8 的 at-least-once+去重键、完全不落 claim/lease 底座 → 否（P8 两处 ADR 显式后置 P9，账要还；且 DoD 要"单机多进程 in-scope"）。
- 关联：`ADR-0021`/`ADR-0038`（本 ADR 落其后置项）/`ADR-0011`/`ADR-0013`/`ADR-0016`/`ADR-0022`/`ADR-0043`；HARD-CONSTRAINTS C2/C6/C12/C13/C15/C16/C18；design/02 §10（投递幂等、视图从事件重建）；peer：wuu `agentcontrol/worker_execution_lease.go`/`delivery.go`、hermes `gateway/delivery_ledger.py`（MIT，取形状不搬传输）。
