# Questor 记忆层（三层 + 检索 + 蒸馏，P4 设计地基）

> 与 [`01-state-model.md`](./01-state-model.md) §2(recovery_pointers)、[`04-turn-loop.md`](./04-turn-loop.md) §7(压缩四档) 交叉。
> 定位：**长期记忆是独立子系统，与运行态 L1 分离**；写必经 `Command→StorePort`（C4），模型永不拿裸向量句柄。

## 0. 铁律
- 记忆读写全收口 `MemoryStore`（Harness 侧），策略/工具只发 `MemoryWrite` Command、经 `memory_search` 拿回 `(path,start_line,end_line,snippet)`；**绝不直连向量库**（C4）。
- **文件/记录为真源、索引为派生投影**：`sync()` 扫盘重建、stale 行 reconcile；索引损坏可重建。
- I3：压缩产出的 `summary` 写记忆时**只写浓缩文本，绝不写 delta**。

## 1. 三层 + 蒸馏
- **core（`MEMORY.md`）**：常绿精华索引，注入每次 system prompt（截断"取尾部保最新"）。
- **daily（`memory/YYYY-MM-DD.md`）**：流水，懒建；**short→long 由"压缩丢弃"驱动**：`_trim_messages`/overflow 把被丢消息摘要后 append 进当天（异步后台、claim-then-commit 去重、失败可重试）。
- **dreams（Deep Dream 蒸馏产物）**：周期性把 daily 蒸馏回 core + 梦境日记；**原子写、输入哈希去重、只删不编、空哨兵跳过**；dreams **不进索引**（防近重复噪声）。

## 2. 检索栈（混合）
`向量(cosine) + 关键词(FTS5 unicode61 / trigram-CJK / LIKE 兜底)` → **rank-normalize 加权融合** → **时间衰减**(daily 半衰、core 常绿) → 可选 rerank → 命中热度 boost(默认关)。
- 融合用 rank 归一(0,1]加权，**不是 RRF**；向量失败静默降级关键词，不抛。
- **P4 实现现状（校正）**：关键词只有**两档**（unicode61→LIKE，CJK 靠 LIKE 命中）；**trigram-CJK 未实现→后置 P10**；无 embedding 时向量通道恒空、降级关键词-only。上表为**目标栈**，非全已落。

## 3. 压缩↔记忆桥（接 04 §7 四档梯度）
- **L2 归档留指针**（默认，零信息丢）：`recovery_pointers=(seq_from,seq_to)+CoveredHash 锚、fail-closed`（01 §13）。
- **L2' 蒸馏**：压缩丢弃区可选发 `MemoryWrite(distill=被压区)` Command → reduce → StorePort（写 daily/检索层）。
- 归档=置 inactive 不物删；rotation（开子 session）作整线可恢复的另一提交模式。

## 4. StorePort 可插拔
`VectorBackend(upsert/delete/search)` 抽象 + SQLite 实现；`StorePort` 同款切；无 embedding 降级关键词-only。

## 5. 落地节奏
- v1（P4）：三层文件真源 + 混合检索 + Deep Dream + 写收口 StorePort。
- v1 后：rerank/热度、可恢复压缩完整判据、记忆审计。

## 6. 待定 / P4 落定
- **已定形（P4）**：chunk schema = `MemoryChunk{id,scope,source,path,start_line,end_line,text,hash,embedding,metadata}`（`contracts/memory.py`）；`CHUNKER_VERSION=1`（切块策略变更触发 `sync` 全量重建）；时间衰减半衰期默认 30d（`MemoryStrategyConfig.half_life_days`，配置化）。`recovery_pointers` 定为 typed `(seq_from, seq_to, covered_hash)` + 读前 fail-closed（ADR-0024，快照 v3）。
- **仍待定（后置）**：rerank / 命中热度 boost（默认关）；`covered_hash` 写锚生产者随压缩落地（P10）；artifact GC / 真源修剪（P10）；跨进程记忆 exactly-once（P9）。**向量 embedding 持久化（P10）**：`sync()` 全量重建会清空 `memory_chunks.embedding`（文件真源不存向量），且重建重排 chunk id——P4 无生产 embedding 路径、向量通道恒空降级关键词；P10 接 embedding 时须按**内容 hash** 重算/持久化，不能假设 sync 保留向量、也不能拿 chunk id 做稳定外键。
- **口径修正（P4）**：§1“short→long 由压缩丢弃驱动”与 `disable_compaction=True` 冲突 → daily 生产者改为**显式 `WriteMemory` + run-完成边界 flush**（ADR-0025）；压缩→L2' 蒸馏桥只留接缝、活路 P10。
- **P10 落地（2026-10-19，ADR-0048/0050）**：`covered_hash` 写锚生产者已随可恢复压缩转正落地（`kernel/compaction.py`+`state/reduce.py::CompactContext`，fail-closed 读校验）；§3 L2' 蒸馏桥已接活（压缩丢弃区→`WriteMemory(distill)`→daily，可检索回读）；artifact **孤儿 GC** 已落（`FileSystemArtifactStore.gc_orphans`，可达性）。**仍后置 P10**：session 级 artifact 真回收 + `event_log` 裁剪（ADR-0050 绑裁剪、与压缩恢复/回放权威冲突）；向量 embedding 持久化/trigram-CJK 检索（本 Phase 未做，eval 据实降级关键词-only）。
