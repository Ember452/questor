# ADR-0033: 带外投影收口为 bus 级只读订阅（D-P7-A，收口 plan/05 §0.4 缺口）

- 状态：✅（2026-10-17）
- 背景：`observability/projection.log_envelope()` 把 `Envelope → LogEntry` 投进主干日志（带外、只读旁路）。P5 只在 `surfaces/cli.py:264` 的 `_stream`（**逐消费者**）里调用它，HTTP sidecar 路径（`surfaces/http_sse.py:148-158` `stream()`）出 SSE 帧但**完全不投带外日志**（`plan/05 §0.4` 明记"HTTP sidecar 带外投影暂未覆盖"，P5 审计 §6 记 UNVERIFIED）。P7 桌面会**同时存在多个 surface 订阅者**（SSE + CLI + …）：若沿用"逐消费者各调 `log_envelope`"，同一条 Envelope 会被**多消费者各投一份**进主干日志。`docs/pitfalls.md` 第 2 条（节流签名看不见 `context`/`fields` 的区分信息 → 合并/丢行同罪）与 HARD **C6**（折叠/合并同罪）、**C20**（观测面不得成第二载体）共同判此为红线。收口点 P5 已写死为"bus 级只读订阅"，本 ADR 正式落地、不再顺延。
- 决策：
  - 在**组合根/serve 装配处**（ADR-0032 的 `--serve`）为**该 run 的 `InProcessEventBus`** 挂**恰好一条只读订阅者**，统一对**所有** surface 的消费者做 `Envelope→LogEntry` 投影；这条订阅者旁路读事件、**不 reduce、不改 state、不新增事件 type**。
  - **删除 `surfaces/cli.py:264` 的逐消费者 `log_envelope` 调用**——改由这一处 bus 级订阅覆盖，CLI 面不再自带投影。
  - **落点分层**：只读订阅者装配属**组合根/surfaces**；`projection.py`（唯一允许 import contracts 的适配层）**复用不改**；observability 九个内核文件（S7）**零依赖不破**（T10 由 `check_log_kernel_isolation --self-test` 守）。
  - **判据（"每条恰投一份"）**：任意 run 的每条可持久 `Envelope` 在主干日志里**恰一条**带 `run_id` 的事件类带外行；多挂一个 surface 订阅者**不增份**；把 `log_envelope` 塞回逐消费者 → 用例必**红**。
- 后果（正面 / 代价 / 需持续守）：
  - 正面：带外投影与 surface 数量解耦，桌面/sidecar 路径的事件类带外行补齐（plan/05 §0.4 缺口收口）；协议 schema **零 diff**（只读旁路，不触事件形状）。
  - 代价：需保证"一个 run 恰挂一条 bus 级投影订阅"的装配不变式（多装即双投），由 §4 单投 canary 用例真进程 grep 守（`pitfalls #1` 纪律③：测真子进程而非 `LogEntry` 构造）。
  - 需持续守：任何新 surface（IM/OpenAI 兼容）接入都**不得**再引入逐消费者 `log_envelope`；带外行签名仍受 pitfalls #2（跨 run/跨实体不合并、错误类绕过节流）约束。
- 备选（被否）：
  1. 保留逐消费者调用、靠日志去重兜底 → 否：`pitfalls #2` 明确"签名看不见区分信息"，节流既会误合又会漏投，去重不是投影正确性的替代。
  2. 只在 `EventServer` 一处投、CLI 保留自投 → 否：两半各自正确、合起来对同一 run 双投，正是 C6/C20 违例。
  3. 把投影塞进 `bus.emit` 内联 → 否：`bus`（L2）不 import `observability` 适配层（保持 kernel↔observability 方向与九内核零依赖 S7），且把观测副作用焊进内核路径。
- 关联：`docs/pitfalls.md` #2、`HARD-CONSTRAINTS` C6/C20、`STRUCTURE` S6/S7、[`ADR-0027`](./0027-observability-logging-foundation.md)（含复审修正）、`docs/plan/05-p5-skills-mcp.md` §0.4、`docs/audit/P5-review-2026-10-17.md` §6、`docs/plan/07-p7-desktop-shell.md` §0.3 D-P7-A / T2/T10。
