# ADR-0042: 事件 additive——`peer_started`/`peer_ended` 定形（只增 type、不 bump `v`、三处 lockstep）

- 状态：✅（2026-10-18，P8 开工前置门；实现见 `docs/plan/08-p8-multi-agent-dag.md` T1/T2/T8/T10）
- 背景：`design/02-event-protocol.md §7`（`:71`）把"子agent→`peer_started/peer_ended` + `node(kind=subagent)`"列为协议"只增不改够用"的**生长场景预留名**，但 `contracts/events.py:251-273` 的 20 个 `EventType` **从未落地这两个名**（同 P6 占位从未落地、由 ADR-0036 就地记账的形状）。P8 需把它们定形，且严守 C6/C15/C18/C20 + 不破信封/关联键/终止序（`design/02 §0/§6`）。
- 决策（全部 additive）：
  - **新增两 type**：`EventType.PEER_STARTED="peer_started"`、`EventType.PEER_ENDED="peer_ended"`；外部协议计数 **20 → 22**。**非终态事件**，不参与 `run_cancelled` 先于 `run_completed` 的终止序（C13）。
  - **`data` 字段（有界、只关联键 + 标量状态 + 指针，无正文）**：
    - `peer_started` = `{parent_run_id, child_run_id, node_id}`；`kind` 由 `node_id` 对应的 `TaskNode.kind=subagent` 隐含，不单列。
    - `peer_ended` = `{parent_run_id, child_run_id, node_id, terminal_status, result_ref?, resumable_hint}`；`terminal_status ∈ {completed, failed, cancelled}`；`result_ref` 为不透明 artifact 指针字符串（**绝不含 abs path**，ADR-0019）；`resumable_hint` bool（承 wuu `mailbox.go::isResumableMailboxStatus`）。
  - **`node_updated` 白名单不扩**：保持 `{node_id, status, title, parent_id}`（[ADR-0035](./0035-p7-additive-tool-event-and-node-shape.md) 已定形）。`objective`/`deps`/`assigned_run_id` 属内部权威态，**不外发**；前端要富节点走只读端点拉快照，不塞事件。
  - **不 bump `EVENT_SCHEMA_VERSION`（=1 不动）**：additive 加 type 是 C6 允许项；先例——[ADR-0024](./0024-memory-contract-evolution.md)（`memory_written` 使 19→20）、[ADR-0035](./0035-p7-additive-tool-event-and-node-shape.md)（加字段）。破坏性才 bump。
  - **三处 lockstep（C15）**：`contracts/events.py`（`EventType` + `EXTERNAL_EVENT_FIELDS` 显式 frozenset——新 type 不在白名单会被 `project()` 当"未知外部类型"丢弃）⟂ `protocol/event.schema.json`（`enum` 两项 + `$defs` 两体，每体 `additionalProperties:false`、字符串 `maxLength` 定死 + `if/then` 两支）⟂ TS codegen 重生成。`check_protocol_schema --check` 断言四处（enum==$defs==branches==白名单键集）一致；`--self-test` 补 `peer_*` valid fixture + 超 maxLength/未知字段 bad。
  - **C20 投影**：`peer_started/peer_ended` **不进 `observability/projection.py::_DATA_KEYS`**（正文/关联键非日志白名单）——多 agent 排障看事件流；若 P10 刀 3 要进日志再另评（plan 待拍板 D-6）。
- 后果：
  - 正面：`design/02 §7` 的"生长场景"当场兑现（证明只增不改够用）；旧消费者忽略未知 type（C6）、事件流体积有上界；快照协议零改动（type 集变、`v` 不变）。
  - 代价：扩 `EXTERNAL_EVENT_FIELDS` 须同步 `protocol/event.schema.json` `$defs` + fixture + TS codegen；`check_projection_whitelist` 守白名单不含正文。
- 备选（被否）：
  1. **复用 `node_updated` 塞 peer 语义**（不加 type）：把"跨 run 关联"混进"单节点状态"，字段膨胀且违反语义分离、丢 `parent_run_id/child_run_id` 关联 → 否。
  2. **把委派正文/结果塞 `peer_ended.data`**：无界载荷拖垮内存/SQLite/SSE/prompt + 事件成第二载体 → 否（C18/C20，ADR-0019 已否；正文走 `result_ref` 指针）。
  3. **bump `v`**：additive 却破坏向后兼容、逼全消费者升级 → 否（违 C6）。
- 关联：HARD-CONSTRAINTS C6/C11/C13/C15/C18/C20；ADR-0024/0034/0035；`contracts/events.py`、`kernel/events.py::EXTERNAL_EVENT_FIELDS`、`protocol/event.schema.json`、`observability/projection.py`；`design/02 §3/§6/§7`；`docs/plan/08-p8-multi-agent-dag.md` §4.1。
