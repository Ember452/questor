# ADR-0020: 耐久写门 + log 权威顺序（durable 永不半 tool_use）

- 状态：✅（2026-10-16）
- 背景：P2 已具备 `StorePort`/`SQLiteStore`（append/replay/sequence_head/save_checkpoint/latest_checkpoint）、完整 `snapshot` v2、`checkpoint.closed_prefix` 纯函数。但接线有两处破口：① `kernel/loop.py::_checkpoint` 在每次 turn 边界把**整条 `context.items`** 全量落快照，哪怕末尾是一条尚无 `tool_result` 的 `tool_use`——durable 里因此可能存"半截 tool call"；② 事件与快照谁权威、崩溃落在两者之间时以谁为准，未写死。P3 的"kill 后重启续跑"判据要求 durable 态永远 role-pair 自洽，否则重建出的 `context` 会被原样喂回 provider（Anthropic/OpenAI 强制 `tool_use↔tool_result` 成对，直接 4xx）。R03 实扒（CowAgent `step_writer.py:53-64,128-144`、DeepCode `store.py:1-24`）显示更稳的默认是**写门截断**、读时 repair 只兜底。
- 决策：
  - **写门默认**：落 checkpoint 前把持久化的 `context.items` 截到 `closed_prefix(items)`（每个 `tool_use` 都已配 `tool_result` 的最长前缀）；未闭合尾部扣住不落，其 id 记入 checkpoint 的 `pending_tool_calls`。durable **永不持半 tool_use**。
  - **log 权威**：`event_log` 是唯一真相。落库顺序固定为 **先 append 本 turn 的耐久事件（`BEGIN IMMEDIATE` 原子）→ 再 `save_checkpoint`**；快照缺失/损坏 → 由 `replay` + `from_snapshot` 路径回退重放重建，不反向以快照抹事件。
  - **读时 repair 兜底**：恢复仍扫 `pending_tool_calls` 补合成 `tool_result`（复用 `reduce` 的 `_backfill_open_calls`/`RecordToolResult` 语义，绝不直改 ledger），只覆盖"两次 flush 之间被 kill"的窄窗口。
  - **delta 不入 durable**：`LIVE_ONLY`（text/reasoning delta、tool_progress、heartbeat、usage）继续经 `project` 转发而不写 `event_log`（承 design/01 I3、ADR-0005）。
  - checkpoint `kind` 支持 `auto|pre_tool|post_tool|pre_compact`（design/01 §5），P3 实装 turn 边界 `auto` 与工具前后补点，`pre_compact` 留占位（压缩在 P10）。
- 后果：正面——重建/恢复出的 provider 上下文永远成对，续跑不 4xx；快照损坏可回退重放，无双写漂移。代价——事件日志单调增长，归档/GC 后置 P10；`pending_tool_calls` 只在窄窗口非空（v1 串行工具，单 turn 至多一条）。
- 备选（被否）：
  1. 全量快照不做写门（=P2 现状）：durable 可含未配对 `tool_use`，resume 喂回 provider 直接 4xx，且要靠读时 repair 频繁兜底 → 否。
  2. 快照权威、事件可被快照覆盖：破坏 append-only 审计账本，回放/审计失真，违 C13 → 否。
  3. 纯事件溯源、去掉快照：长会话每次恢复重放全史，读放大（ADR-0005 已否）→ 否。
- 关联：ADR-0004/0005/0011/0013/0019；HARD-CONSTRAINTS C2/C5/C7/C13；[`../design/01-state-model.md`](../design/01-state-model.md) §5/§9/§12(I3/I4)/§13、[`../design/04-turn-loop.md`](../design/04-turn-loop.md) §7。
