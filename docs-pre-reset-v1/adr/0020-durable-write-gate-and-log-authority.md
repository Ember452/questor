# ADR-0020: 耐久 checkpoint 与 log/snapshot 权威（完整快照 + 派发侧补齐）

- 状态：✅（2026-10-16）
- 背景：P2 已具备 `StorePort`/`SQLiteStore`（append/replay/sequence_head/save_checkpoint/latest_checkpoint）、完整 `snapshot` v2、`checkpoint.closed_prefix` 纯函数。但接线有两处破口：① `kernel/loop.py::_checkpoint` 在每次 turn 边界把**整条 `context.items`** 全量落快照，哪怕末尾是一条尚无 `tool_result` 的 `tool_use`——durable 里因此可能存"半截 tool call"；② 事件与快照谁权威、崩溃落在两者之间时以谁为准，未写死。P3 的"kill 后重启续跑"判据要求 durable 态永远 role-pair 自洽，否则重建出的 `context` 会被原样喂回 provider（Anthropic/OpenAI 强制 `tool_use↔tool_result` 成对，直接 4xx）。R03 实扒（CowAgent `step_writer.py:53-64,128-144`、DeepCode `store.py:1-24`）提示可用**写门截断**免修半态，但本项目 `awaiting_approval` 需跨重启续跑，截断与之冲突，故最终选"完整快照 + 派发侧补齐"（见下修正）。
- 决策（2026-10-16 实现期修正：写门与 HITL 续跑的权衡见下）：
  - **完整权威快照**：checkpoint 落**全量权威 `Run`**（含未闭合 tool_use 与其 `pending_tool_calls`、`awaiting_approval` 审批），**不截断** `context.items`。原因：`awaiting_approval` 是必须跨重启续跑的稳态，截断会抹掉待审审批（`test_p2_hitl_resume` 断言其存活）。provider 配对由 [ADR-0021](./0021-cross-process-resume.md) 的 **re-dispatch-before-provider** 保证：续跑进入 provider 前，先在同一安全点补齐/重派所有未闭合 `tool_use`，绝不把半截 `tool_use` 喂回 provider。
  - **`closed_prefix` 用途收窄**：`state/checkpoint.py::closed_prefix`/`open_tool_use_ids` 用于**识别在途集**（写入 `pending_tool_calls`、判定重派范围），不再用于截断 durable。
  - **稳态补点**：`loop` 在 turn 边界（`auto`）、审批挂起（`pre_tool`）、工具落库（`post_tool`）三处各打一个 checkpoint，把"崩溃→重跑一个工具"的 at-least-once 窗口收到最小。
  - **log 权威（事件维度） + 快照权威（状态维度）**：`event_log` 是耐久事件唯一真相（SSE `after_seq` 客户端重放 + 审计），`checkpoints` 是权威状态快照。落库顺序固定 **先 append 耐久事件（`BEGIN IMMEDIATE` 原子）→ 再 `save_checkpoint`**；快照损坏 → 退到次近完好快照 + 由 ADR-0021 重派在途调用（输出事件不可 reduce 回灌状态，C5）。`rebuild_run` 把 `run.seq` 对齐到 `sequence_head`，续跑取号不复用旧 seq。
  - **delta 不入 durable**：`LIVE_ONLY`（text/reasoning delta、tool_progress、heartbeat、usage）继续经 `project` 转发而不写 `event_log`（承 design/01 I3、ADR-0005）。
  - checkpoint `kind` 支持 `auto|pre_tool|post_tool|pre_compact`（design/01 §5），P3 实装 turn 边界 `auto` 与工具前后补点，`pre_compact` 留占位（压缩在 P10）。
- 后果：正面——重建/恢复出的 provider 上下文永远成对，续跑不 4xx；快照损坏可回退重放，无双写漂移。代价——事件日志单调增长，归档/GC 后置 P10；`pending_tool_calls` 只在窄窗口非空（v1 串行工具，单 turn 至多一条）。
- 备选（被否）：
  1. 截断 `context.items` 到 closed_prefix（本 ADR 初稿）：会抹掉必须续跑的 `awaiting_approval` 稳态，与 HITL 恢复冲突 → 修正为"完整快照 + 派发侧补齐"。
  2. 全量快照不记 `pending_tool_calls`：崩溃时无法判定哪些调用需重派，续跑可能漏配或重复 → 否。
  3. 快照权威、事件可被快照覆盖：破坏 append-only 审计账本，回放/审计失真，违 C13 → 否。
  4. 纯事件溯源、去掉快照：长会话每次恢复重放全史，读放大（ADR-0005 已否）→ 否。
- 关联：ADR-0004/0005/0011/0013/0019；HARD-CONSTRAINTS C2/C5/C7/C13；[`../design/01-state-model.md`](../design/01-state-model.md) §5/§9/§12(I3/I4)/§13、[`../design/04-turn-loop.md`](../design/04-turn-loop.md) §7。
