# R06 — 压缩边界 + 记忆层取证（可恢复压缩 / recovery pointer / 记忆写收口）

> 只读外部扫描取证报告，服务两处目标：**① questor 04 `docs/design/04-turn-loop.md` §7 的"压缩边界"**；**② 未来 `docs/design/05-memory.md`（三层 / 检索 / 蒸馏）**。
> 三个重点问题：**可恢复压缩 vs 丢弃式**、**recovery pointer 形态**、**记忆写必经 `Command→StorePort`**。
> 扫描对象：`hermes-agent-main/agent/*`、`CowAgent-master/agent/memory/* + knowledge/*`、`wuu-main/internal/{agent,compact,session}/*`（wuu 压缩为 **Go**，非 py）。
> 铁律：**读全不抽样、只提增量与缺口**。所有结论附 `文件:行号`；命名不同处如实标注。

---

## 0. 一句话结论

- **"可恢复压缩"不是一个开关，是一条梯度**：确定性丢弃 → 摘要替换 → 整体归档(留指针) → 蒸馏进长期记忆。三家各占不同档，questor 目前只写了"摘要替换 + 留指针"一档，**缺"归档留指针"的独立档与"压缩即写记忆"的接缝**。
- **recovery pointer 最优形态 = 指向 append-only 日志的单调序号区间(Seg/Seq)，并带一个语义哈希锚(CoveredHash)做 fail-closed**——这正好落在 questor 01 §5/§9"events append-only + seq"上，比"字节偏移 / 独立消息 ID"更契合事件溯源（见 [01 §11 已定]）。
- **记忆写必经 `Command→StorePort` 已被 Cow 印证且可加强**：Cow 全部读写收口 `MemoryManager→MemoryStorage`，模型只经 `memory_search` 拿回 `(path, start_line, end_line, snippet)`，**从不拿到裸向量句柄**——与 questor C4 完全同构；且 Cow 把"压缩丢弃的内容"直接 flush 成日记，是 questor 04↔05 之间当前缺失的接缝。

---

## 1. hermes —— 可恢复压缩的"归档 + 指针 + 双提交模式"

### 1.1 压缩边界：head / middle / tail 三段 + turn 边界触发
- **`compress()` 主流程 = 四阶段**：Phase1 廉价裁剪工具结果 → Phase2 定边界 → Phase3 生成摘要(可跳 LLM) → Phase4 组装 `head + summary + tail`。
  — `context_compressor.py:5534-5641`
- **保护区（边界锚点）**：head = system prompt + **衰减的 `protect_first_n`**（防早期 user 轮"化石化"跨多次压缩）——`context_compressor.py:4671-4678`；tail = 按 **token 预算**从后往前累加，锚定 last-user/last-assistant、**工具组永不拆**——`context_compressor.py:5073-5079`、`_align_boundary_forward` 仅跳过孤儿 tool 结果 `4646-4650`、`_align_boundary_backward` 把 compress-end 拉回不拆工具组 `4680-4688`。
- **Phase1 只裁 tool-result 正文，tool-call 参数绝不改写**——`context_compressor.py:5573-5576`（"tool-call args untouched"）。
- **触发点是 turn 边界 + 溢出**：压缩触发闭集 `manual | turn_start_threshold | pre_api | post_tool | idle | engine_preflight | overflow | between_turns | proactive_prune`——`compaction_events.py:37-40`。**印证 questor 04 L3"只在 turn 边界压缩"**。

### 1.2 可恢复压缩 vs 丢弃式：核心是"原地归档 active=0，不物理删"
- **摘要标记携带元数据键**，标记"这段是被压缩产物、含不含 user 轮、能否被 micro 覆写"：
  `COMPRESSED_SUMMARY_METADATA_KEY="_compressed_summary"`、`COMPRESSED_SUMMARY_HAS_USER_TURN_KEY`、`MICRO_COMPACT_MARKER_KEY`、`MODEL_ONLY_DISPLAY_METADATA_KEY`——`context_compressor.py:296-303`；组装摘要行时写入 `5656-5660`；`_SUMMARY_END_MARKER`（"respond to the message below, not the summary above"）防弱模型把摘要当新输入 `501`。
- **被压原文 = 原地归档，不删**：commit 把压缩器握过的行按 `_row_id` 归档到 DB（active=0 留在盘上），`compressed` 集成为新 active 集；`_db_persisted` 内在标记判定是否已落盘——`context_compressor.py:319-322`。归档覆盖率计算（哪些 `_row_id` 被这次压缩"吞掉"、哪些是无 id 需按 role+content+tool_call_id 匹配的悬空行）——`conversation_compression_archive.py:48-73`（`held_archive_coverage`）、`101-136`（`coverage_for_commit`，命中不了就退回 watermark）。
- **两种提交模式：in-place vs session-rotation**：`split_status ∈ {in_place_committed, rotated_committed}`——`compaction_events.py:50,64`，映射到事件字段 `in_place / session_rotated`——`192-193`。**rotation = 开子 session、老 session 原样留着**（最彻底的可恢复：直接引用旧 session）。
- **micro-compaction 的关键纪律（直接可抄进 questor）**：**默认关闭**，因每趟重写 prompt prefix 会击穿 provider 提示缓存——`micro_compaction.py:3-5`；**user 轮永不吸收**（"user turns are never absorbed … verbatim user text"）——`micro_compaction.py:65-93`（`_find_one_exchange`），marker `HAS_USER_TURN=False` `469-471`；**resume 从幸存 marker 里 rehydrate 滚动摘要** `42-63`；落盘走 `archive_and_compact` 原地归档 `408-452`；合并相邻 user 轮时 `record_absorbed_message(prev, msg)` 记"合并见证人"（prev 保 uid、记 msg 的）`518`。
  — **完全对齐 questor 01 §2"只压中段、user/assistant 文本不删"**。
- **native（provider 服务端）压缩 = 不透明检查点指针**：OpenAI Responses `context_management=[{type:compaction, compact_threshold}]` 产出带 `encrypted_content` 的 `compaction` item（provider 自持累积上下文，非本地可读原文）——`native_compaction.py:1-8`、`has_compaction_checkpoint` 判据 `encrypted_content` 非空 `398-406`；本地压缩器保留为 fallback、native 阈值钳在本地触发之下（安全垫 8192）`25`；`prune_pre_checkpoint_items`：**围绕最新 checkpoint 重建**，**user 明文按预算逐字保留、summary 整段保留绝不切片** `240-363`；服务端压缩是"provider 自持的有损边界（无法先打 pre-compress checkpoint）"，故 checkpoint-aware 本地压缩器才是权威 `122-127`。
- **刚交付的 assistant 回复必须跨过压缩 commit 存活**：引擎把最新回复折进摘要区时，commit 处强制把它重新插回 tail（严格 role 交替优先于恢复）——`conversation_compression_reply_anchor.py:18-137`，特别是 `99-112` 拒绝造出 assistant;assistant。

### 1.3 命名陷阱（questor 术语必须避让）
- **`context_pin.py` 不是"消息 pin"**：是 `model.context_length` 这个**窗口大小钉值**覆盖 provider 元数据——`context_pin.py:1-24`。questor 若要"保护某条不被压"的概念，**别叫 pin**，用 hermes 真实做法（`protect_first_n` / anchor / marker 元数据）。
- **`context_references.py` 不是 recovery pointer**：是 `@file/@diff/@url` 的 **prompt 注入展开**（软/硬预算 25%/50%、越权凭据 fail-closed）——`context_references.py:1, 212-213, 523-546`。**但它藏了一个真正可借鉴的"内容指针"范式**：文件过大/二进制**不内联，而是回一个"on-disk 指针块"**（"available on disk at `path`，用工具去 read_file/search"），让模型**按需回读**而非塞爆窗口——`646-677`。这正是"recovery pointer 的另一种形态：指向磁盘/工具可再取的路径"。
- **`compression_marker.py` 是丢弃式省略标记（不可恢复）**：把工具参数中段裁掉写 `⟪...omitted...⟫`，内容真丢了——`compression_marker.py:19-25, 62-87`；设计点是"标记不可被模型模仿/复用"，非可恢复。

---

## 2. CowAgent —— 三层记忆 + 混合检索 + Deep Dream 蒸馏（05 母本）

### 2.1 三层记忆（文件为真源，SQLite 索引为派生投影）
- **布局**：`MEMORY.md`(global，注入每次 system prompt，≤50 条) / `memory/YYYY-MM-DD.md`(daily) / `memory/dreams/*.md`(梦境日记) / `memory/evolution/*.md`——`memory/summarizer.py:1-10`、`memory/service.py:6-10`。
- **short→long 的写入由"压缩丢弃"驱动**（**这是 questor 04↔05 的关键接缝**）：`MemoryFlushManager` 在 **① context trim（`_trim_messages` 丢旧轮）② context overflow（API 拒）** 两种情形，把**被丢弃的消息** LLM 摘要后**追加进当天 daily 文件**——`memory/summarizer.py:194-203`（类 docstring 触发源）；`reason ∈ trim|overflow|daily_summary` 决定段落头 `423-427`；**异步后台线程跑摘要**，主回复不被阻塞 `319-330`；**claim-then-commit 去重哈希**（in-flight vs flushed 两套，失败释放回可重试）`288-344`。
- **一次 LLM 调用同时喂两处**：`context_summary_callback` 把 `[DAILY]` 摘要**既落盘、又注回 live messages 做上下文续接**——`memory/summarizer.py:282-287, 388-392`。**对 questor 的启示**：压缩产 `summary` 给策略读(01 §2)与写记忆(05)可共享一次摘要。
- **Deep Dream 蒸馏（周期性 长期化）**：`deep_dream(lookback_days)` 读 `MEMORY.md + 近期 daily` → LLM 产出 `[MEMORY]`(重写 MEMORY.md，合并/萃取/消歧/清理) + `[DREAM]`(梦境日记) → `write_text_atomic` 落盘——`memory/summarizer.py:511-648`（prompt `56-158`）；**按 daily_content_hash 去重**（同一天同内容不重复做梦）`544-554`；**transient 错误重试 3 次** `567-613`；空哨兵 `无/None`=无价值不写 `186-191`；**只删不编**（严禁造材料外信息）prompt 硬约束 `64,108`。

### 2.2 混合检索（向量 + 关键词 + 融合 + 时间衰减 + rerank）
- **写路径全部收口 `MemoryManager`→`MemoryStorage`，模型拿不到裸库句柄**（= questor C4 实证）：`add_memory` chunk→embed→`save_chunks_batch` `manager.py:244-317`；`sync` 扫盘重建索引（文件真源、索引投影、stale 行 reconcile）`319-589`。
- **recovery pointer 形态（记忆侧）= `(path, start_line, end_line)` 行区间**：`MemoryChunk{id,user_id,scope(shared|user|session),source(memory|session),path,start_line,end_line,text,embedding,hash,metadata}`——`storage.py:104-116`；`SearchResult{path,start_line,end_line,score,snippet,source,user_id}`——`120-128`；chunk_id = `md5(path:start:end:part)` `manager.py:649-655`。
- **读路径经工具封装**：`memory_search` 只回 `path (lines a-b) + score + snippet`，模型再 `memory_get` 按行区间回读原文——`tools/memory/memory_search.py:108-113`；提示"要写记忆就往 MEMORY.md/daily 写文件" `95`。
- **混合融合算法 = rank-normalize 到 (0,1] + 只在命中的通道上加权平均 + 时间衰减**（**不是 RRF**）：`_merge_results` `manager.py:742-799`；`_rank_normalize` 按名次线性归一 `722-740`；`_compute_temporal_decay` 仅对**带日期 daily 文件**指数半衰(默认 30 天)，MEMORY.md/knowledge 常绿 `657-697`；权重归一防 NaN/负 `699-720`。
- **关键词三档降级**：FTS5 unicode61(纯 ASCII) → trigram FTS5(CJK/混合) → LIKE 兜底，BM25 排序——`storage.py:898-951`、`_search_fts5:953-1010`；`bm25_rank_to_score` 归一 `999`。
- **向量后端可插拔（= StorePort 抽象）**：`VectorBackend(upsert/delete/search)` 抽象 + `SQLiteVectorBackend`（cosine，numpy/pure 双路）——`vector_backend.py:40-63, 104-178`；**无 embedding 时静默降级为关键词 only** `manager.py:181-201`；**rerank 可选 cross-encoder 覆写分数** `801-842` + 命中热度 boost（默认关）`857-918`。
- **knowledge 与 memory 同一索引、不同 source**：`sync` 把 `knowledge/**.md` 以 `source="knowledge"` 索进同一套（dreams 与 index.md/log.md 排除）——`manager.py:359-396`；`KnowledgeService` 只做文件读写 + 复用 `memory_manager` 触发 reindex——`knowledge/service.py:28-163`。

---

## 3. wuu —— recovery pointer 的最完整范式（Go）

wuu **三种压缩策略并存**，把"可恢复梯度"演全了：

### 3.1 A 档：传统摘要替换（丢弃式，进文本摘要）
- `CompactWithBudget`：定 `keepStart` → `toSummarize=[:keepStart]` 交 LLM 摘要 → 结果 = `systemPrefix + [Conversation summary] 系统行 + protectedCurrentUser + toKeep`——`compact/compact.go:197-235`；`ConversationSummaryPrefix="[Conversation summary]"` 保持稳定以利持久化与缓存命中 `59-66`。
- `Budget{Context,Input,OutputReserve,KeepRecent,Target,SummaryInput}` tokens——`158-175`；**摘要输入上限 80k**、下限 4k `29-31`；**raw tail 默认 20k**（provider 中立）`126-129`；**defensive trim：摘要请求自身溢出就丢最旧一条重试 ≤3 次**（防"压缩→溢出→再压缩"死锁）`115-149`；native 与 portable 二选一：优先 provider-native checkpoint，不支持/瞬态耗尽才退回文本摘要 `237-340`。

### 3.2 B 档：`fresh_context`——**真正的"可恢复压缩"（不摘要，整体归档 + 留指针）**
- **一句话：把整段活跃 transcript 归档到持久 History（不摘要），只留一条隐藏系统"恢复"消息带 Seq 指针**，让模型用检索工具回读。`buildFreshContext` 注释直书 "**releases the archived transcript without summarizing it**"——`agent/fresh_context.go:52-54`。
- **recovery pointer 形态（旗舰证据）**：恢复消息内容 `"The previous active transcript is archived through History Seq %d … Recover … with history_search and history_read … Start at Seq %d"`——`fresh_context.go:67`；`HistoryArchive{Seqs []int（与消息对齐，0=未落盘）, HeadSeq int}` 记物理地址 `36-41`；恢复行 `Role:system, Hidden:true, Origin:internal, Cause:fresh_context` `75-77`。
  — **直接回答 questor 01 I2"指针指 events 日志偏移 vs 独立消息 ID"：wuu 选的是单调 Seq（≈日志游标/序号），不是字节偏移也不是独立 UUID**。这与 questor 01 §5/§9"events append-only + seq"天然同构。
- **保真与安全边界**：保留 system 前缀 + 若装得下就带上**最新一条 user 指令** `95-112`；必须严格更小 `ErrFreshContextNotSmaller` `25,113-115`；**required 图/文件不能被指针替代则拒绝** `ErrFreshContextTooLarge` `100-110`；工具调用历史必须合法 `ValidateToolCallHistory` `116-118`。
- **控制权仍在 Harness**：`new_context` 是**模型调的一个工具**（只能最近一批 tool 结果请求、失败/截断无控制效力）——`fresh_context.go:141-161`；宿主 `FreshContextCommitFunc` **原子安装 checkpoint** `45-48`；重复转换抑制 `deferRepeatedContextTransition` `163-176`；配合**模型自持的 working notes + Checkpoint(path,revision)** 按需回读 `72-89,184-185`（`context_window` reminder 教模型写 goal/constraints/decisions/progress/remaining + Seq refs 的检查点）。

### 3.3 C 档：`CompactionNote`——**带哈希锚的可交付 handoff（fail-closed）**
- 结构 `{Markdown, CoveredMessages(它覆盖了前缀多少条), CoveredHash}`——`agent/compaction_note.go:18-22`；`CoveredHash = sha256(前缀去掉 Seq/ToolInvocationID 后的语义哈希)` `77-86`。
- **指针一致性校验 = 历史被编辑/重写/分叉即失效**：`validCompactionNote` 重算 `messages[:CoveredMessages]` 的哈希比对，不符就当没有——`88-93,134-137`。→ **questor recovery_pointers 应带一个 anchor/hash，读取前校验，历史漂移则 fail-closed**（对应 01 §12 I7"已发 Event 不撤销"下的稳健回读）。
- **并发安全**：`ConditionalCompactionNoteStore.CompareAndSwap` 防更旧后台 fork 覆写已刷新 checkpoint `47-51,215-222`；落**独立会话表 `session_compaction_notes`（不作为聊天消息）**、只保 active 版本不累加——`session/compaction_note.go:14-93`；空 Markdown 可作 tombstone 但锚仍当 CAS 代次 `106-108`。
- **消息带 Seq 前缀喂摘要 fork**：`annotateCompactionNoteHistorySeqs` 把每条 `[History Seq N]` 前缀化 `242-251`。
- **fallback 纪律**：note 失败**只回退一次**到传统压缩；**取消不是恢复请求；失败或未变小的输出绝不替换历史**——`agent/compaction_fallback.go:11-33`。

### 3.4 自适应阈值 & 可插拔压缩器（对齐 questor 04 §10"阈值留 P10"）
- **观测驱动**：`reactiveCompactTarget = lastSuccessful - margin(margin=lastSuccessful/5, min 4k)` `agent/adaptive_compact.go:99-116`；`applyAdaptiveCompactBudget` 用"同 contract 历史成功下界的一半"或"失败请求的一半"做首次探针、几何退避，并**识别不可恢复溢出**（固定面+当前轮+reserve > 目标就明确报错）`147-217`；探针按 **provider/model/endpoint 的 opaque contract key** 隔离 `42-97`。
- **保护区**：`protectedDurableTokens = 非摘要 system 前缀 + 最后一条 user` `219-234`（与 hermes head/tail、Cow 保留明文同源）。
- **压缩器可插拔注册表**：`CompactionProvider{Key,Compact,Priority}`、一个 run 内**最高优先级生效**、`Default` 宿主策略、按 plugin/generation 清理 `agent/compaction_registry.go:24-147`；`ErrCompactionUnavailable` 触发退回默认 `11-15`。→ **对应 questor STRUCTURE `kernel/` 压缩 + 能力注册表：压缩策略是 L2 内核持有、可被扩展替换的能力，非策略层**。
- **持久 lineage 不破坏**：`compaction_lineage_journal_test.go:46-102`——无论 native 可用与否，压缩须**保全 SQLite 推理操作 journal 的父子血缘**（拒绝悬空身份/跨流边）。→ **questor：压缩属 Kernel reduce、走 append-only events，绝不能撕裂审计/回放链（01 §12 I7、04 §7）**。

---

## 4. 三问定论（给 04 与 05 的设计取向）

### 4.1 可恢复压缩 vs 丢弃式 —— 建议 questor 显式写成"四档梯度"
| 档 | 动作 | 丢原文? | 谁可恢复 | 三家实证 |
|---|---|---|---|---|
| L0 确定性裁剪 | prune tool-result 正文 / elide marker / drop blank echo | 是(低价值) | 不可 | hermes `context_compressor.py:5573-5576`、`compression_marker.py:62-87` |
| L1 摘要替换 | 中段→LLM 摘要，产 summary marker（`HAS_USER_TURN` 元数据） | 是(浓缩) | 半（摘要在手，原文丢） | hermes `5615-5660`；wuu `compact.go:197-235`；Cow flush `summarizer.py:262-436` |
| L2 **整体归档留指针** | 原文全量落 append-only History，active 只留 Seq 指针 | **否** | **是**（`history_read/search` 回读） | wuu `fresh_context.go:52-120`；hermes `conversation_compression_archive.py` + `active=0` |
| L2' 蒸馏进长期记忆 | 被丢区浓缩写长期层，混合检索按需召回 | 是(进记忆) | 是（经检索回读） | Cow daily→Deep Dream→MEMORY.md `summarizer.py:511-648` + `manager.py:137-242` |

- **缺口（04 §7 现只有"摘要+留指针"一档）**：建议 04 §7 改成引用此梯度，并**把 L2 定为默认**（对齐事件溯源，零信息丢），L1 作为"预算极紧/无需回读"降级；**L2' 的写记忆走 05，压缩时发一条 `MemoryWrite` Command**（补上 04↔05 接缝）。
- **红线不变**：L0/L1/L2 全在 **turn 边界**、只由 **Harness 触发**（策略仅 advisory）——hermes `between_turns` 触发 `compaction_events.py:37-40`、wuu `new_context` 工具请求但宿主提交 `fresh_context.go:45-48,141-161` 双双印证 01 §12 I2 / 04 §7/L3。

### 4.2 recovery pointer 形态 —— 定论：**Seq 区间 + 哈希锚 + 归档不物删**
- **形态**：`(run_id, seq_from, seq_to)` 指向 `events`/`messages` 的 append-only 序号区间（**不用字节偏移，不用独立 UUID**）。理由：与 questor 01 §5 Checkpoint/§9 events append-only 天然同构；wuu `HistoryArchive.Seqs/HeadSeq` `fresh_context.go:36-41,67` 是活样板。
- **必带 anchor**：仿 wuu `CompactionNote.CoveredHash`（对覆盖前缀的**语义哈希、剔除线程局部 Seq/调用 id**）`compaction_note.go:18-22,77-93`——**读取前先校验 anchor，历史被改写/分叉即 fail-closed**，绝不返旧内容。
- **归档 = 置 inactive，不物理删**（hermes `archive_and_compact` active=0 `context_compressor.py:319-322` + `conversation_compression_archive.py`）——支撑 undo/branch/restore；**rotation（开子 session）作为整线可恢复的另一提交模式** `compaction_events.py:50,64,192-193`。
- **记忆侧指针**：`(path, start_line, end_line)` 行区间（Cow `storage.py:104-128`）；大内容"on-disk 指针块 + 工具回读"范式（hermes oversized 文件不内联、给路径让 read_file 切片 `context_references.py:646-677`）。

### 4.3 记忆写必经 `Command→StorePort`（C4）—— Cow 全证 + questor 补强点
- **收口**：Cow 无一处旁路——`add_memory/sync` 全经 `MemoryManager→MemoryStorage` `manager.py:244-317,319-589`；读只经 `memory_search` 工具回 `(path,lines,snippet)` `tools/memory/memory_search.py:108-113`；**模型永不拿到向量库/SQLite 裸句柄**。→ **即 questor 01 §11"写记忆/状态一律 Command→Harness→StorePort；读经 StorePort、策略无裸句柄(C4)"的落地实证**。
- **可插拔后端**：`VectorBackend` 抽象（upsert/delete/search）+ SQLite 实现 `vector_backend.py:40-63,65-178`——questor `StorePort` 直接照此切接口，向量库实现不越界（STRUCTURE §7 S1/S4）。
- **补强接缝**：**压缩丢弃即触发写记忆**（Cow trim/overflow → flush daily `summarizer.py:194-203,262-436`）。questor 应把"压缩产 L2 指针的同时，可选发 `MemoryWrite(distill=被压区) Command` → L2 reduce → StorePort"写成 05 的一条主路径；**遵守 I3：只写浓缩文本，绝不写 delta**。
- **失败与去重**：claim-then-commit（失败回滚可重试）`summarizer.py:288-344`；周期蒸馏 `Deep Dream` 走原子写 + 输入哈希去重 + transient 重试 `511-648`——对应 STRUCTURE "写必经 reduce、状态不被撕裂"。

---

## 5. 未来 `docs/design/05-memory.md` 直接可用的取料清单

1. **三层命名与生命周期**：全局(EVERGREEN) / 日记(带日期、可时间衰减) / 蒸馏产物(Deep Dream 生成、常不作为独立检索源)——Cow `summarizer.py:1-10` + `manager.py:657-697`（decay）+ `manager.py:359-364`（dreams 排除索引）。
2. **写路径**：`MemoryWrite` Command → reduce → `StorePort`；**文件/记录为真源、索引为派生投影、reconcile 清 stale**——Cow `manager.py:319-589`。
3. **检索栈**：`向量(cosine) + 关键词(FTS5 unicode61/trigram-CJK/LIKE) → rank-normalize 加权融合 → 时间衰减 → 可选 rerank → 热度 boost(默认关)`——Cow `manager.py:137-242,742-842` + `storage.py:898-1010` + `vector_backend.py:104-178`。
4. **切块**：行区间 + overlap + markdown 结构感知（标题边界、贪心跨标题合并、尾块折叠）+ `CHUNKER_VERSION` 触发重建——Cow `chunker.py:22-231`。
5. **chunk/schema 字段**：`id,user_id,scope,source,path,start_line,end_line,text,embedding,hash,metadata`——Cow `storage.py:104-116`（questor 落 StorePort 时的候选 shape）。
6. **蒸馏纪律**：只删不编 / 合并消歧 / 空哨兵跳过 / 原子写 / 重试——Cow `summarizer.py:64-77,511-648`。
7. **压缩↔记忆桥**：见 §4.3 补强接缝。

---

## 6. 对 questor 现有文档的增量/缺口（只列要动的）

- **04 §7**：把单档"可恢复压缩(产 summary+recovery_pointers)"改写为 **§4.1 四档梯度**，明确 **L2 归档留 Seq 指针为默认**、L1 为极紧预算降级、并**新增"压缩时可选发 `MemoryWrite` Command"的 05 接缝**。
- **01 §2 / §11 未决项**：把 `recovery_pointers[]` 的形态**定为 `(seq_from, seq_to) + CoveredHash 锚`**（原"events 偏移 vs 独立消息 ID"的悬案，据 wuu 取 Seq 侧），并加一条不变式：**读指针前校验 anchor，历史漂移 fail-closed**（补 §12，对应 I7）。
- **01 §2 保护区**：`compaction_floor` 语义可参照 hermes"head=system+衰减 protect_first_n / tail=token 预算 / 工具组原子"与 wuu `protectedDurableTokens`，但**字段细节仍按 C11 留 v0 后锁**（此处只补设计口径，不锁字段）。
- **术语避让**：questor 文档**勿用 `context_pin`**（hermes 该名=窗口大小钉值，非消息保护）；**"message pin/anchor" 概念**用 `protected/anchor/marker` 表述；`recovery pointer` 与 `@-reference/context_references`（prompt 注入）明确区分。
- **红线呼应**：三家一致证明"压缩=Kernel 行为、只在 turn 边界、策略仅 advisory、事件 append-only 不可反哺、写记忆必经 StorePort"——04/01/HARD-CONSTRAINTS(C2/C4/C5/C7/C13) 无需改，仅在设计口径上引用本报告作外部实证锚点。

---

## 附：本次扫描覆盖文件（读全）
- **hermes**：`context_compressor.py`(定向读全 compress/head/tail/marker 5534-5660/4671-4720/248-506)、`context_compressor_summary.py`、`context_compressor_prellm.py`、`conversation_compression_archive.py`、`conversation_compression_manual.py`、`conversation_compression_reply_anchor.py`、`micro_compaction.py`、`native_compaction.py`、`relay_compaction.py`、`context_pin.py`、`context_references.py`、`compression_marker.py`、`compaction_events.py`。
- **CowAgent**：`memory/summarizer.py`、`memory/manager.py`、`memory/storage.py`(定向读全 schema/融合/检索 100-175/860-1010)、`memory/chunker.py`、`memory/service.py`、`memory/reranker.py`、`memory/vector_backend.py`、`tools/memory/memory_search.py`、`knowledge/service.py`(结构)。
- **wuu**：`internal/agent/{adaptive_compact,fresh_context,compaction_registry,compaction_note,compaction_fallback}.go`、`internal/session/compaction_note.go`、`internal/compact/compact.go`(定向读全 Budget/Compact/native 55-360)、`internal/agent/compaction_lineage_journal_test.go`(行为契约)。
- **未逐行读全但已定位（后续如需可补扫）**：hermes `context_compressor.py` 全文(5847)、`conversation_compression.py`(4560)、`turn_context_compaction.py`、`compaction_display.py`；Cow `memory/conversation_store.py`(3050，session 作用域存储)；wuu `fresh_context_persistence_test.go`。本报告结论均建立在已读代码的 `文件:行号` 之上，未对未读部分做外推断言。
