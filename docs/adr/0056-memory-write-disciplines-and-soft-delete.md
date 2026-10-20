# ADR-0056: 记忆写回八纪律与"变更史 = 事实流"（不建 memory_history 表）

- 状态：✅（2026-10-21，B9/c1–c5）
- supersedes：本文档 v3 §6.4-6 与 T9 早先的 `memory_history(old,new,event,…)` 逐条版本链设计
  （§20 C-7 已采 PLAN 否决，本 ADR 是那次裁决的落地记录）
- 背景：个人 agent 的"记忆越用越脏"有四条来路：①夜间批吃光用户配额；②抽取输入无界、把
  有界摘录当成可重放历史；③入站正文带密钥/媒体；④被用户否定过的旧事实与替代事实同时可召回。
  同时 questor 的 C5/C13 纪律要求"事实流是唯一权威"，任何 per-memory 版本链表都是第二真相。
- 决策：
  1. **八条纪律全部落进 `memory/write_policy.py`**（可调用，不是注释）：配额闸
     （``MIN_RATE_LIMIT_REMAINING_PERCENT=10``）、双上限抽取（``MAX_EXTRACT_BYTES`` /
     ``MAX_RECORD_BYTES`` + **保留最新、恢复源序** + 明写"不是完整历史、不得用作 resume"）、
     入站脱敏（复用 `observability.redact`，新增公共 `redact_secrets` 而非另造规则）、
     媒体占位符、归因位 `attributed_to∈{user,assistant}`、软删位 + `memory_deleted` 事件、
     `expires_at` 与衰减**分离**、代际平行根（`memory_store_v2`，**拒绝符号链接根**）。
  2. **撤回 = 索引软删位 + 一条 durable 事件**：`DeleteMemory` Command → `memory_deleted`
     （durable）→ 消费点经 `MemoryStorePort.soft_delete(entry_id, idempotency_key=…)` 置
     `is_deleted=1` 并从 FTS 摸掉。**真源 md 文件不删**、**不建 `memory_history` 表**；
     "这条被改过几次"只能从事件流投影。
  3. **sync 不复活已撤回记忆**：wipe+rebuild 前先收集 `is_deleted` 行的 (path, 行区间)，
     重建后按**区间重叠**重新标记（write 时的区间算插入点、chunker 重建算 markdown 节边界，
     精确等值会漏；hash 也会因节头入正文而失配）。
  4. **supersede 先退役再写替代**（`memory/consolidate.py`）：顺序不可反，否则两步之间
     矛盾事实同时可召回；无 `soft_delete` 能力时**如实报告降级**，不假装退役成功。
  5. **巩固不阻塞回复**：per-session 锁 + 有界重试（``MAX_DISTILL_ATTEMPTS=2``）；蒸馏器抛错
     只留痕；配额不足返回 `quota_hold`，不补跑 N 次。
  6. **写路径仍唯一**：所有写入经 `WriteMemory`→reduce→消费点；`TurnSettler` 是 turn 边界的
     唯一写回者（surface 不旁路）；B14 的用户显式改写走 `UpdateMemory`/`DeleteMemory`，不是第二条旁路。
- 后果：
  - 正面：撤回可回放且不多一张无界增长表；过期与衰减职责分离（排序 vs 退出）；被否定过的事实
    真的不再回来；巩固/蒸馏有配额与重试边界。
  - 代价：`memory_deleted` 是 durable 事件（每条撤回占一个 seq）；软删行仍占索引存储（物理修剪
    绑 `event_log` 裁剪，ADR-0050 已后置）；分层保留期默认值写进 `TIER_RETENTION_DAYS`，改它属行为变更。
  - 需持续守：任何人想加"记忆版本链表"= 直接违反 §20 C-7 与本 ADR，必须先推翻裁决；
    `is_deleted`/`expires_at` 过滤**必须在 SQL 里**，不能靠下游筛（否则"命中未过滤"会悄悄回流）。
- 备选（被否）：
  1. **`memory_history(old,new,event,…)` 表**：否——第二真相 + 千文件项目里又一张无界表（§20 C-7）。
  2. **物理删除 md 段落**：否——文件是真源；删真源会让"事实流 + 快照"与文件分叉，且回放不再等价。
  3. **靠衰减排序挤掉过期/被否定条目**：否——排序不是退出，条目仍会被召回（正是"越用越脏"的病根）。
  4. **入站不脱敏、靠日志侧兜**：否——记忆会回灌进 prompt，泄漏面比日志大得多。
- 关联：v3 §6.4/§6.5/§13 B9/§20.3 C-7、`ADR-0024/0025`（typed 写载荷与离线收口）、`ADR-0050`（卫生回收边界）；
  `contracts/memory.py`、`contracts/events.py`、`state/reduce.py`、`kernel/loop.py`、`kernel/settle.py`、
  `memory/write_policy.py`、`memory/consolidate.py`、`memory/sync.py`、`providers/store_memory_sqlite.py`；
  `tests/unit/test_memory_disciplines.py`、`tests/unit/test_memory_consolidation.py`。
