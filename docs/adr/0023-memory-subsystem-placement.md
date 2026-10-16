# ADR-0023: 记忆子系统定位与分层裁定（独立子系统包，非新编号层；落库经独立 MemoryStorePort）

- 状态：✅（2026-10-16，决策定；实现见 [`../plan/04-memory-soul.md`](../plan/04-memory-soul.md) T5–T18）
- 背景：P4 要把长期记忆做成独立子系统（[`../design/06-memory.md`](../design/06-memory.md) §0"长期记忆是独立子系统，与运行态 L1 分离"），且 [`../STRUCTURE.md`](../STRUCTURE.md) §9 明确"长期记忆子系统落 `src/questor/memory/`（与 `state/` 分离）"。但出现两处需在实现前钉死的结构性歧义：① 有口径把记忆称作"L7 独立子系统"，而 [`../design/00-layering.md`](../design/00-layering.md) §2 / [`../STRUCTURE.md`](../STRUCTURE.md) §6 定义的 **L7 = Shell/UI（Tauri 桌面）**，八层 L0–L7 已被 `.importlinter` 契约 + ruff `banned-api` + 自研 AST 检查器三道守卫编码（HARD C1/C14/C15），若把"记忆"重编号为 L7 会与 Shell 冲突并撕裂三道守卫；② [`../design/01-state-model.md`](../design/01-state-model.md) §9 的 `StorePort` 自 P3 起承载的是 **event-log（append 事件 + 快照 + 双游标 seq/gseq）**，语义专一，R03 实扒 D-P1（CowAgent `conversation_store.py:85-93`）证明"运行追踪/消息历史分表故障隔离"更稳，把记忆向量/FTS 表塞进同一库会一处损坏拖垮运行态。
- 决策：
  - **记忆 = 跨层的独立子系统包 `src/questor/memory/`（`state/` 的 peer），不是新的编号层**；它按职责分别落进既有八层，依赖方向仍"外层→内层"、绝不反向：
    - **L0 `contracts/memory.py`**：记忆数据类（`MemoryChunk`/`MemorySearchResult`/`RecoveryPointer`/typed `MemoryWrite`）+ `MemoryStorePort`/`VectorBackend`/`MemoryStrategyPort` 抽象协议；只放数据与 Port（S4，HARD C11）。
    - **L1 `state/reduce.py`**：`WriteMemory` 命令 → 产内部 `memory_written` 事件 + 返回新 `Domain_State`；**记忆正文绝不进 `Domain_State`**（至多有界指针/artifact 引用）。
    - **L2 `kernel/`**：唯一 Command 消费者在 `WriteMemory` 进入 `reduce` 后，经**注入的 `MemoryStorePort`** 落库（热路径写收口，C4/C16）；检索读路径亦由 Harness 经该端口返回授权结果、按字段白名单投影（ADR-0026）。压缩↔记忆桥（L2' distill）仅在此留接缝，其生产者随压缩后置 P10。
    - **L4 `policy/`**：记忆注入/召回作为**可插拔策略**（05 §5），经 `PolicyView.memory` 只读投影消费，不持底层句柄。
    - **L5 `providers/store_memory_sqlite.py`**：`MemoryStorePort` + `SQLiteVectorBackend` 的具体实现，落在**独立 `memory.db`**。
  - **落库经独立 `MemoryStorePort` + 专用 `memory.db`，与 P3 的 event-log `StorePort`/库分家**：两者共享同一套纪律范式（单一 `_SCHEMA` authority + 幂等 DDL + `meta(store_schema_version)` 未知版本 fail-closed + `BEGIN IMMEDIATE`，复用 P3/ADR-0022），但物理分库以保**故障隔离**（索引损坏可 `sync()` 扫盘重建、不牵动运行态事件溯源）。`MemoryStorePort` 仍是 **Harness 持有的接口**，满足 HARD C4"策略/工具无裸句柄"的意图（不是旁路）。
- 后果：正面——记忆与运行态解耦，满足 DoD⑤（分层不腐、事件协议只增不改）；`memory/` 算法可独立演进/替换（DoD④）；分库使记忆索引损坏的爆炸半径被限制在记忆子系统内。代价——多一套 schema 版本闸门与一个 DB 文件的 GC/清理（后置 P10）；`.importlinter`/ruff/AST 三守卫需新增对 `memory`/`providers.store_memory_sqlite` 的边界条目（plan/04 T17）。
- 备选（被否）：
  1. 把记忆重编号为 L7：与既有 L7=Shell 冲突、破 import-linter/ruff/AST 三道机器守卫的层号方向（HARD C1/C14/C15）→ 否。
  2. 复用 P3 event-log `StorePort`/同库承载记忆向量/FTS 表：违故障隔离（R03 D-P1），一处损坏拖垮运行态；且语义混淆"事件溯源 log"与"知识层"→ 否。
  3. 记忆正文写进 `Domain_State`：破坏 state/memory 分离（DoD⑤）、撑爆快照、污染回放/续传 → 否。
  4. 记忆算法内联进 `kernel/loop.py`：破"可插拔不耦合 Kernel"（DoD④、05 §5）→ 否。
- 关联：[`../design/06-memory.md`](../design/06-memory.md) §0/§4；[`../design/00-layering.md`](../design/00-layering.md) §2；[`../design/01-state-model.md`](../design/01-state-model.md) §9/§11；[`../STRUCTURE.md`](../STRUCTURE.md) §6/§9；HARD-CONSTRAINTS C1/C4/C11/C14/C15/C16；ADR-0003/0004/0005/0013/0022/0025/0026；R03 D-P1、R06 §2/§4.3。
