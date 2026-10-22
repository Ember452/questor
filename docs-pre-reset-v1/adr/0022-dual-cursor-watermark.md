# ADR-0022: 双游标物化到 StorePort（per-run 逻辑 seq + 全局物理 watermark）

- 状态：✅（2026-10-16）
- 背景：ADR-0011 定了"续传要 per-run 稳定游标 + 跨 run catch-up/watermark 要全局单调物理序"两条游标，但 P2 的 `SQLiteStore.event_log` 只有 `PRIMARY KEY (run_id, seq)` 一条 per-run 逻辑序，**全局物理序未物化**。P3 落地持久化时若不把第二条游标补上，等到 P7（桌面订阅）/P9（对外 API）要做"补齐我错过的所有 run"时又要改表形、改 `StorePort`，属破坏性返工。R03（DeepCode `event_repository.py:21-56,89-112`：逻辑 per-thread `sequence` + 物理全局 `rowid` watermark）是已验证范式。
- 决策：
  - **物化两条游标，互不混用**：
    - `seq`（既有）= per-run 逻辑序，`SSE after_seq` 续传/回放游标，对应 02 信封 `seq`；由 `reduce` 权威分配、`append` 沿用（ADR-0011）。
    - `gseq`（新增）= 全局单调物理序，跨 run changelog watermark；SQLite 以 `event_log` 自增物理列承载（或 `INTEGER PRIMARY KEY AUTOINCREMENT` 代理键），建索引 `idx_events_gseq`。delta/heartbeat 属 live-only、**两条游标都不占**（design/02 §10）。
  - `StorePort` 纯**增量**扩展（不破既有签名/信封/关联键，C6）：`watermark() -> int`（当前全局头部）、`replay_global(after_watermark, limit) -> list[JsonObject]`（跨 run catch-up，返回携 `run_id`+`seq`+`gseq`）、`list_unfinished_runs() -> tuple[str, ...]`（供 `--resume` 枚举非终态 run）、`checkpoint_seq(run_id) -> int | None`（最近快照 seq，供尾重放起点）。
  - **schema 单一 authority**：`store_sqlite._SCHEMA` 为唯一 DDL 真源、幂等 `IF NOT EXISTS`；新增 `meta(key,value)` 表存 `store_schema_version`，读时未知版本 **fail-closed**（不猜测半升级表形，R03 E-P1）。写路径继续 `BEGIN IMMEDIATE` 持写锁（C2 单写者）。
  - 跨 run 一致性：`append` 事务内同时更新 `runs(run_id, head_seq, status, updated_at)` 记账表，供 `list_unfinished_runs` O(1) 查询；`runs` 表与 `event_log`/`checkpoints` 故障隔离（损坏只降级枚举、不拖垮历史，R03 D-P1）。
- 后果：正面——续传（per-run）与全局 catch-up（跨 run）从 P3 起各有其序、索引清晰，P7/P9 接线不改表；`--resume` 有权威枚举入口。代价——`gseq` 与 `seq` 需在传输/存储两侧写清不混用；watermark 永不回收（防 ABA），裁剪策略后置 P10。
- 备选（被否）：
  1. 只用一条 `seq` 两头兼顾：跨 run 无稳定全序，catch-up 要么漏要么重（ADR-0011 已述"单一 seq 两头不讨好"）→ 否。
  2. 全局序用向量钟/Lamport：单机单写者不需要因果偏序，徒增复杂度（C12）→ 否。
  3. `replay_global` 直接扫 `event_log` 不加 `gseq` 列：每次 catch-up 全表扫，读放大 → 否，建物理列+索引。
  4. P7/P9 再补 watermark：届时改 `StorePort` + 迁移历史表形 = 破坏性返工 → 否，P3 前置物化。
- 关联：ADR-0005/0011/0013/0020/0021；HARD-CONSTRAINTS C6/C13/C15；[`../design/01-state-model.md`](../design/01-state-model.md) §7/§9/§13、[`../design/02-event-protocol.md`](../design/02-event-protocol.md) §4/§10。
