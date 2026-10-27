# ADR 0010: journal 写序与快照格式（journal write order and snapshot format）

- Status: Proposed (draft; implementation deferred to Phase B0)
- Date: 2026-10-27
- Deciders: Questor maintainers

## Context

会话持久化现状是**全量 JSON 覆写快照**：`platform/session_storage.py:22` 钉
`SNAPSHOT_SCHEMA_VERSION = 1`，`:93` 把 `schema_version` 写进载荷，`:105` 用
`json.dumps` 整文件覆写（全文件 238 行）。这个形态在单进程、低频写入下够用，但
personal 形态上线后宿主是 7×24 常驻进程，两个缺口随即暴露：

1. **崩溃窗口丢数据**：覆写瞬间进程死亡 = 整份会话损坏或回退到上一份快照；
2. **"先展示后落库"的时序隐患**：若产出先可见、快照后写，崩溃即丢已展示回合。

其中第 2 条是**行为时序**问题，不需要本 ADR——"先落库再展示"（写序前移）作为
行为时序修正归计划 04 的 A2 刀直接实施。需要 ADR 的是第 1 条背后的**存储格式
迁移**：[ADR-0002](0002-target-structure.md) Decision 第 3 条已冻结
"`kernel` 这个名字为 durable 保留，现在不建……要引入必须先单独 ADR + 预算 +
排期"。本 ADR 就是那个"单独 ADR"的方向草案；**实施与否在 B0 另行裁决**。

## Decision（草案方向，实施前可修订）

1. **双载体**：journal（append-only 事件日志，逐条追加）+ 周期快照（折叠态，
   现有 JSON 形态演进）。恢复 = 加载快照 + 重放其后 journal 至最后一致点；
   journal 超过阈值触发新快照并截断。参照 pi `packages/durable/` 的"先落库再
   展示、重启续跑、Compaction 是带重试上限的持久任务"机制（跨语言，只取机制
   不搬代码）。

2. **schemaVersion 读旧写新**：快照与 journal 各带版本字段；升级路径只允许
   "读旧版本 → 内存归一 → 写新版本"，现役守卫
   `tests/fixtures/persistence/v1/session.json`（不带 `schema_version` 的
   旧 fixture）必须继续加载成功。

3. **`kernel/` 是否随实施立项，在 B0 裁决**：若实施，落位与预算按
   ADR-0002 第 3 条走独立排期；不实施则本 ADR 保持 Proposed，不动现有快照格式。

4. **与本 ADR 无关的事**（避免范围蔓延）：A2 的写序前移（行为时序，无 schema
   变更）；`running → interrupted` 的重启恢复语义（同属行为时序）；工具调用台账
   （A1 的旁路 JSONL，独立于会话真相）。

## Alternatives considered

- **维持全量覆写快照**：B0 前的默认状态。写序前移（A2）已解掉"丢已提交回合"
  的最痛场景，覆写损坏窗口对单用户可接受——这正是实施可以推迟的理由。
- **直接上完整 durable spine（事件流 + `reduce()` + upcast + 投影层）**：拒绝。
  ADR-0002 Alternatives 已否——独立大立项，先跑快照模型，真需要 rewind/审计/
  跳端续跑时再立项。
- **只加 journal、去掉快照**：拒绝。恢复代价随会话长度单调上涨，周期快照是
  必要的折叠点。

## Consequences

- 若实施：崩溃窗口从"整份快照"缩到"最后一条 journal"；rewind/会话树/fork/
  历史搜索（计划 04 非目标清单里的存储迁移族）从此有了落脚的格式前提。
- 代价：写入路径多一层 journal 管理；旧快照兼容代码长期存在；`SNAPSHOT_SCHEMA_VERSION`
  的递增纪律从此是硬约束。
- 必须保留：旧 fixture 可加载；journal 与快照都不做第二真相（会话真相唯一，
  记忆/索引是派生物，对齐 [ADR-0004](0004-memory-provider-contract.md) 不变式）。

## Verification

- 实施（若发生）自带红用例：强杀进程后已提交回合不丢；旧版本快照 + 空 journal
  可加载；重放幂等（同一 journal 重放两次结果一致）。
- 本 ADR 为草案，当前仅受文档守卫约束（`scripts/guards/check_doc_cross_refs.py`）；
  不触发任何结构或行为变化。
