# Questor 计划 4（P4）· 记忆 v1（灵魂）· 开发计划（READ-ONLY 规划）

> 起手必读：[`AGENTS.md §4.5`](../../AGENTS.md) · [`docs/ROADMAP.md §3`](../ROADMAP.md) · [`docs/design/HARD-CONSTRAINTS.md`](../design/HARD-CONSTRAINTS.md)
> **本文是规划文档**：套 [`_TEMPLATE.md`](./_TEMPLATE.md) 分节。§0 未填完=不可开工。
> 契约：[`design/06-memory.md`](../design/06-memory.md)（P4 主文档）/ [`01`](../design/01-state-model.md) §2/§5/§9/§13 / [`02`](../design/02-event-protocol.md) §5/§6 / [`04`](../design/04-turn-loop.md) §7 / [`05`](../design/05-policy.md) §5；实扒：[`references/R06`](../references/R06-compaction-memory.md)/[`R03`](../references/R03-state-persistence.md)；决策：[`adr/0004`](../adr/0004-state-mutation-model.md)/[`0005`](../adr/0005-state-storage.md)/[`0011`](../adr/0011-seq-semantics.md)/[`0013`](../adr/0013-run-command-inbox.md)/[`0019`](../adr/0019-bounded-artifact-projection.md)/[`0020`](../adr/0020-durable-write-gate-and-log-authority.md)/[`0021`](../adr/0021-cross-process-resume.md)/[`0022`](../adr/0022-dual-cursor-watermark.md)；前序实况：[`plan/03`](./03-p3-persistence-resume.md)、[`audit/P3-review`](../audit/P3-review-2026-10-16.md)。
> 分支：`feat/p4-memory-soul`。**进入条件已满足**：P3 经 PR #21（merge commit `4ab9d91`）合入 `main`；实现阶段从**最新 main** 切 `feat/p4-memory-soul`（隔离 worktree，见 §10）。

## 0. Peer-Repo 扫描（AGENTS §4.5 硬门禁；证据均实 Grep/Read 核过行号）

**先重列 `project-main/` 目录**（`Get-ChildItem -Directory` 当下 15 个业务/参考目录；参考实现仓 12 个）：`hermes-agent-main / wuu-main / DeepCode-main / CowAgent-master / MetaGPT-main / crewAI-main / OpenManus-main / GenericAgent-main / autogen-main / Agent-S-main / EvoFlow-main / cordis-main`。逐能力取证如下。

| 能力 | 扫描仓（`repo:path:line`，已核验） | 结论（复用/改造/自写） | 说明 · 许可/署名注意 |
|---|---|---|---|
| 短期/工作记忆（core 常绿、注入 system prompt） | DeepCode `core/harness/memory.py:129,197,242,282-329`（`MemoryPointer`/`parse_memory_index`/`project_instructions`）；CowAgent `agent/memory/summarizer.py:1-10`（`MEMORY.md` 布局） | 改造 | 借 DeepCode"指针索引"范式做 core 层（真源=md 文件、注入截尾保最新）；Questor 落 `contracts/memory.py` 数据类 + `memory/` 渲染，不逐行搬 |
| 情节记忆（daily 流水、写入收口） | hermes `agent/memory_manager.py:391,599,747,854`（`MemoryManager`/`sync_all`/`commit_session_boundary_async`/`on_memory_write`）；CowAgent `agent/memory/manager.py:244,319`（`add_memory`/`sync`） | 改造 | hermes "会话边界异步 flush" 直接映射 P4 的 **run-完成→daily** 生产者（替代被后置 P10 的压缩 flush）；写全收口、模型不拿裸句柄 = C4 实证 |
| 语义记忆 / Deep Dream 蒸馏 | CowAgent `agent/memory/summarizer.py:178-182,262,511-648`（`_dream_*_prompt`/`flush_from_messages`/`deep_dream(lookback_days)`）；hermes 夜间定时蒸馏（`cron` auto-distillation，`website/.../userStories.json:3343`） | 改造 | Cow `deep_dream` 的 **原子写+输入 hash 去重+只删不编+空哨兵跳过** 全盘采纳；调度器（cron）非本阶段（hermes 靠 cron 插件，归 P8/cron），P4 只做**离线批入口** `--dream` |
| 向量检索（cosine、可插拔后端） | CowAgent `agent/memory/vector_backend.py:40-63,104-178`（`VectorBackend` upsert/delete/search + SQLite cosine）；crewAI `lib/crewai/src/crewai/memory/storage/lancedb_storage.py`/`qdrant_edge_storage.py`、`memory/recall_flow.py:58`；MetaGPT `metagpt/memory/memory_storage.py:61`（`search_similar(k=4)`） | 改造 | 采纳 Cow `VectorBackend` 抽象同款切 Questor `MemoryStorePort`；**embedding 缺省静默降级关键词-only**（Cow `manager.py:181-201`），真 embedding provider 标 UNVERIFIED（CI 无 key） |
| 全文检索（FTS5/CJK） | CowAgent `agent/memory/storage.py:898-951,953-1010`（unicode61→trigram-CJK→LIKE 三档降级、BM25）；R06 §2.2 | 改造（部分） | **P4 实现两档 unicode61→LIKE**（CJK 靠 LIKE 命中）；**trigram-CJK 未实现→后置 P10**（peer 有三档，本仓未落，**非"已实现待验"**） |
| 混合融合 + 时间衰减 | CowAgent `agent/memory/manager.py:723,742,658`（`_rank_normalize`/`_merge_results`/`_compute_temporal_decay` half_life=30d） | 改造 | design/06 §2 已定 **rank-normalize 加权、非 RRF**；daily 半衰、core 常绿。rerank/热度 boost **默认关、后置** |
| 记忆写入幂等（去重/重试） | CowAgent `agent/memory/summarizer.py:288-344`（claim-then-commit in-flight/flushed 两套、失败可重试）；DeepCode `core/sessions/store.py:1-24`（index 派生可重建） | 改造 | 移植"输入 hash 去重 + 失败释放回可重试"纪律；落 `memory/distill.py` 与 daily flush |
| 记忆压缩 & 恢复指针 CoveredHash | wuu `internal/agent/compaction_note.go:20-21,88-92,211-212`（`CompactionNote{CoveredMessages,CoveredHash}`、`validCompactionNote` 读前校验 fail-closed）；hermes `conversation_compression_archive.py`（active=0 归档不物删）；R06 §4.2 | 改造 | P3 审计 E1 已把 `recovery_pointers` 的 CoveredHash 锚标"随压缩定义、后置 P4/P10"。**P4 只定义 typed `(seq_from,seq_to,covered_hash)` + fail-closed 读校验 + 快照 v3**，其**生产者**（压缩触发）随 `disable_compaction=True` 留 P10，不提前强接活路 |
| 记忆 chunk schema / 切块 | CowAgent `agent/memory/storage.py:104-116,120-128`（`MemoryChunk{id,scope,source,path,start_line,end_line,text,embedding,hash,metadata}`/`SearchResult`）、`chunker.py:22-231`（行区间+overlap+markdown 结构感知+`CHUNKER_VERSION`） | 改造 | 候选 shape 直接对齐 Questor `contracts/memory.py`；`CHUNKER_VERSION` 触发重建留 §6 待定 |

> 许可边界：EvoFlow `evopanel`（PolyForm Noncommercial）**只可只读设计参照、不可搬码进 MIT 项目**；DeepCode/CowAgent/hermes/wuu 复用一律"改造思路 + 标 provenance"，非逐行移植（AGENTS §5.6）。本阶段无前端能力（记忆无 UI，桌面订阅归 P7）。

## 1. 目标与可验证判据（DoD）

**进入条件**（对齐 ROADMAP §1 P4 行）：P3 已完成并**经 PR #21（merge commit `4ab9d91`）合入 `main`**——事件溯源+快照+跨进程 resume+after_seq 真 socket 重连。P3 对抗审计（`audit/P3-review`，锚定不可改）的 §6 六项 must-fix 已在合入前的 commits（`8206f87/23c3b57/318b1bc/e565ec6/e4f81dc/126abdb`）逐项闭合，唯 A2/E1（`recovery_pointers` CoveredHash）与 `driver_id/driver_version` 显式后置到 P4/P9/P10——**这正是 P4 必须接手的正确性前置项**。

**DoD（每条=可复现行为 + 测试样例描述，非"完成感"）**：
- **D①跨会话记住并检索到一件事**：`test_p4_memory_write_readback_cross_session.py` —— 会话 A 经 `WriteMemory`(kind=core/daily) Command 写入一条含唯一标记串（如 `"BLUE-ORCHID-42"`）的事实 → 落 `memory.db` + md 文件真源；**新进程/新会话 B** 启动同一 store，策略调 `memory_search("BLUE-ORCHID-42")` 命中，返回 `(path,start_line,end_line,snippet)` 且 snippet 含该串；断言检索**经 Harness 持有的 `MemoryStorePort`**、策略视图无裸句柄。
- **D②夜间蒸馏（Deep Dream）产出**：`test_p4_deep_dream.py` —— 预置 daily 含 ≥2 条情节（其中一条与既有 core 冲突/冗余）+ 固定 fake distill provider（离线、非真 LLM）→ `--dream` 批处理 → 断言 (a) `MEMORY.md` 被原子重写、合并/消歧该事实；(b) `dreams/*.md` 产梦境日记；(c) **同输入 hash 二次运行为 no-op**（去重）；(d) provider 返空哨兵 `无/None` 时不写、只删不编（断无杜撰新增）。真 LLM 蒸馏**质量**标 UNVERIFIED。
- **D③写/读收口**：`test_p4_memory_single_writer.py` —— 静态：AST 守卫 + `lint-imports` 断言 `policy`/`surfaces`/`capabilities` **不 import** `providers.store_memory_sqlite` 具体实现、策略视图无 `MemoryStorePort` 裸句柄（判红样例：植入一处直连即 `--self-test` 变红）；动态：任何 memory 写**只能**由 `WriteMemory` Command 进入 `reduce`；离线 Deep Dream 走独立 store atomic 写、不触 `Domain_State`（见 §9 裁定 3）。
- **D④算法可插拔不耦合 L2 Kernel**：`test_p4_memory_policy_pluggable.py` —— 检索/蒸馏算法置于 `src/questor/memory/`，经 `MemoryStrategyPort`（或注册项）挂进内核；**默认策略与一个替换策略**（不同 half_life/fusion 权重）跑同一 DoD① 均命中，且全程 `kernel/loop.py` 无 diff（呼应 05 §5、C1/C14）。
- **D⑤记忆子系统与运行态分离、事件协议只增不改**：`memory/` 包与 `state/` 分离（STRUCTURE §9）；`Domain_State` **不含**记忆正文（只可含检索命中的有界投影，经白名单）；外部事件集**新增 1 个可选 type `memory_written`**（bounded：kind/chunk_count/artifact_ref，无原文），`check_protocol_schema --check` 通过、删/改既有 type 判红；既有 P0–P3 全量测试零回归。

## 2. 子任务清单（T0..T18；依赖序：执行基线→ADR→契约→store/引擎→reduce→surfaces→蒸馏→测试→守卫→收尾）

- [ ] **T0 开工基线与 worktree**：按 §10 从**最新 main**（含 P3 `4ab9d91`）切 `feat/p4-memory-soul`（隔离 git worktree）；复跑全质量门取 GO 基线（预期 ≈361 passed / 5 skipped、ruff clean、lint-imports kept、七守卫 self-test 全 PASS、verify_p0 ALL PASS）。验证：基线快照写入本 plan 执行记录。commit：无（基线校验）。
- [ ] **T1 [ADR-0023] 记忆子系统定位与分层裁定**：`docs/adr/0023-memory-subsystem-placement.md`。论点：记忆 = 跨 L0/L2/L4/L5 的独立子系统包 `src/questor/memory/`（`state/` 的 peer），**不重编号为 L7**（L7=Shell，重编号破 import-linter/ruff/AST 三守卫）；落库经**独立 `MemoryStorePort`+`VectorBackend`**、专用 `memory.db` 与 event-log 分家保故障隔离（R03 D-P1）。关联 §9 裁定 1/2。commit：`docs(adr): 0023 memory subsystem placement`。
- [ ] **T2 [ADR-0024] 记忆契约演进（WriteMemory typed + 快照 v3 + covered_hash）**：`docs/adr/0024-memory-contract-evolution.md`。论点：`WriteMemory.payload` 从裸 `JsonObject`（现死 stub）收敛为 typed `MemoryWrite`（v0 锁字段）；新增内部事件 `memory_written` + 外部**可选**投影（C6 只增）；`recovery_pointers` 定义为 `(seq_from,seq_to,covered_hash)`、快照 schema **v2→v3**、未知版本 fail-closed（复用 P3 `contract_version` 闸门）；明确 covered_hash **生产者随压缩后置 P10、P4 仅定形**。关联 §9 裁定 4/5。commit：`docs(adr): 0024 memory contract + snapshot v3`。
- [ ] **T3 [ADR-0025] Deep Dream 离线蒸馏的单写者与原子性纪律**：`docs/adr/0025-memory-distill-atomicity.md`。论点：C2 单写者只强加 `Domain_State`；memory store 为独立持久子系统，其纪律=**文件真源 + `write_text_atomic` + 输入 hash 去重 + claim-then-commit**（Cow `summarizer.py:288-344,511-648`）；离线蒸馏不排活 run 的 Command 队列、不改 `Domain_State`，故不构成第二写者。run-完成→daily flush 亦属此纪律。关联 §9 裁定 3。commit：`docs(adr): 0025 memory distill atomicity`。
- [ ] **T4 [ADR-0026] 混合检索栈与有界投影**：`docs/adr/0026-memory-retrieval-bounded-projection.md`。论点：向量(cosine)+FTS5(unicode61/trigram-CJK/LIKE)→**rank-normalize 加权融合(非 RRF)**→时间衰减；embedding 缺省静默降级关键词-only（不抛）；检索命中原文进 prompt/事件前**字段级白名单 + size cap + artifact 引用**（承 ADR-0019/C18）。commit：`docs(adr): 0026 hybrid retrieval bounded projection`。
- [ ] **T5 契约数据层 `contracts/memory.py`（L0）**：`MemoryChunk{id,scope(shared|user|session),source(core|daily|dreams|knowledge),path,start_line,end_line,text,embedding,hash,metadata}`、`MemorySearchResult{path,start_line,end_line,score,snippet,source}`、`RecoveryPointer{seq_from,seq_to,covered_hash}`、`MemoryWrite`(typed payload、`kind: core|daily|distill`)、`MemoryWriteKind`/`VectorBackend` Port 协议、`MemoryStorePort` 协议。纯 frozen + 不可变集合（C2）。依赖 T1–T4。验证：schema 单测 + 冷导入。commit：`feat(contracts): L0 memory types + MemoryStorePort/VectorBackend`。
- [ ] **T6 契约接线 `contracts/{events,ports,policy,state_schema}.py`**：`events.py` `WriteMemory.payload: JsonObject` → typed `MemoryWrite`（保留 `type="write_memory"`，Command 联合不变）；新增内部 `memory_written` 事件（外部投影可选、bounded）；`policy.py` `PolicyView.memory` 定为**有界检索命中只读投影**（无裸句柄）；`state_schema.py`/`domain_state.py` `recovery_pointers` 从 `tuple[tuple[int,int],...]` 改 typed `RecoveryPointer`（触快照 schema，配 T7）。依赖 T5。验证：protocol schema diff 只增；`lint-imports`。commit：`feat(contracts): typed WriteMemory + memory_written event + PolicyView.memory view`。
- [ ] **T7 快照 schema v3 + fail-closed（L1）**：`state/snapshot.py` 序列化/反序列化 `RecoveryPointer(covered_hash)`、bump `schema_version` v2→v3、未知版本 fail-closed + v2→v3 迁移（`migrated.setdefault`）；沿用 P3 `allow_nan=False`/`require_aware`。依赖 T5/T6。验证：`test_snapshot_v3_roundtrip` + `test_snapshot_rejects_unknown_version`（判红）。commit：`feat(state): snapshot v3 recovery-pointer + fail-closed`。
- [ ] **T8 providers `store_memory_sqlite.py`（L5）**：独立 `memory.db`（与 `event_log` 分家，R03 D-P1）；`_SCHEMA` 单一 authority + 幂等 DDL + `meta(memory_schema_version)` 未知版本 fail-closed（复用 P3 模式）；`memory_chunks` 表（vector 列 + FTS5 虚表 unicode61/trigram）；实现 `MemoryStorePort`(upsert/delete/search/sync/reconcile) + `SQLiteVectorBackend`(cosine)。文件真源=md（core/daily/dreams），索引=派生投影。依赖 T5。验证：`test_memory_store`（版本判红、损坏重建）。commit：`feat(providers): MemoryStorePort SQLite + VectorBackend (isolated memory.db)`。
- [ ] **T9 memory 子系统 `memory/{chunker,sync}.py`**：`chunker.py` 行区间+overlap+markdown 结构感知+`CHUNKER_VERSION` 触发重建（Cow `chunker.py`）；`sync.py` 扫盘重建索引、reconcile stale 行（文件真源、`manager.py:319-589` 范式）。依赖 T8。验证：`test_chunker` + `test_sync_rebuild_after_index_corruption`。commit：`feat(memory): chunker + sync (files authoritative, index derived)`。
- [ ] **T10 memory 检索栈 `memory/{vector_store,keyword,search}.py`**：向量 cosine + FTS5 三档降级 + `_rank_normalize`+`_merge_results` 融合 + `_compute_temporal_decay`(half_life 配置) + embedding 缺省降级关键词-only。算法经 `MemoryStrategyPort` 暴露为**可插拔**（DoD④）。依赖 T8/T9。验证：`test_hybrid_fusion_not_rrf` + `test_temporal_decay` + `test_vector_missing_degrades_to_keyword` + `test_memory_search_pluggable_two_strategies`。commit：`feat(memory): hybrid retrieval (rank-normalize fusion + decay), pluggable strategy`。
- [ ] **T11 reduce `state/reduce.py` WriteMemory 分支（L1/L2）**：`WriteMemory`(typed) → 校验 payload 有界（size cap，超限拒→error 事件，C18）→ 产新 `Domain_State`（**不含记忆正文**，至多有界指针/引用）+ 发内部 `memory_written`；实际落库由 kernel 侧经注入的 `MemoryStorePort` 完成（写必经 Command，旁路=0，C4）。守 I3：只写浓缩文本、绝不写 delta。依赖 T6/T7/T8。验证：`test_memory_single_writer`（旁路赋值 grep=0、判红样例）+ `test_write_memory_bounded_reject`。commit：`feat(state): WriteMemory reduce -> memory_written + StorePort sink`。
- [ ] **T12 memory_search 能力工具 `capabilities/tools/memory_search.py`（L3）**：策略经此工具拿回 `(path,start_line,end_line,snippet)`、无裸句柄；结果经 T4 字段级白名单投影；注册进 `tools/registry.py`（`ToolKind.MEMORY` 已存在）。依赖 T10/T11。验证：`test_memory_search_cross_session`（=DoD①）；断工具不 import `store_memory_sqlite`。commit：`feat(capabilities): memory_search tool (bounded, no raw handle)`。
- [ ] **T13 Deep Dream 离线蒸馏 `memory/distill.py` + run-完成 flush**：`deep_dream(lookback_days)` 读 core+daily→（注入 provider）→ dreams+重写 core，**原子写 + 输入 hash 去重 + 只删不编 + 空哨兵跳过**（Cow `summarizer.py:511-648`）；run 完成边界 `flush_to_daily()`（hermes `commit_session_boundary_async`）把本 run transcript 摘要 append daily、claim-then-commit 去重、失败可重试。**离线/异步、不进活 run 热 loop**（05 §5）。依赖 T9/T10/T11。验证：`test_deep_dream`（=DoD②，fake distill provider）+ `test_deep_dream_hash_dedup_noop` + `test_run_boundary_flush`。commit：`feat(memory): Deep Dream offline distill + run-boundary daily flush`。
- [ ] **T14 surfaces 装配（L6/组合根）**：`__main__.py` 组合根注入 `MemoryStore(impl)`（surfaces 不 import 具体 store，C4/C14）；CLI `--dream` 子命令 + 记忆写/检索走既有 Command Inbox（`WriteMemory` 经 `RunRegistry.submit`，不直 reduce，C16）；HTTP 暴露（如有）仅投 `memory_written`（白名单）+ `POST /runs/{id}/memory` 亦经 inbox。依赖 T11/T12/T13。验证：`test_surfaces_no_concrete_memory_store`（AST 判红）+ 端到端 DoD① 经 CLI。commit：`feat(surfaces): composition-root memory injection + --dream`。
- [ ] **T15 可插拔记忆策略示例（L4）**：`policy/` 内一个把 core 注入 system prompt（截尾保最新）+ 检索命中经白名单并入 `PolicyView` 的示例策略；证明"换记忆策略/调权重不动 Kernel"（DoD④、05 §5）。依赖 T10/T12。验证：默认 vs 替换策略同跑 DoD① 命中、loop.py 零 diff。commit：`feat(policy): memory-aware pluggable policy demo`。
- [ ] **T16 测试与回归**：单元（chunker/fusion/decay/dedup/covered_hash fail-closed/store 版本）；集成（DoD① 跨进程新会话命中、DoD② Deep Dream 产出、DoD③ 单写者）；`test_p4_durability`（记忆写不旁路、live 不入 event_log、memory.db 损坏不拖垮 event_log）；**evals 任务级**（写入→检索→蒸馏召回一条事实的最小回归网，P10 前必备雏形）；冷导入全 `src/questor/**` 逐模块 + `lint-imports` + protocol schema diff。既有 P0–P3 全量零回归。依赖 T5–T15。commit：`test(p4): memory write/retrieval/deep-dream/single-writer + evals`。
- [ ] **T17 守卫 `scripts/check_memory_layering.py` + CI wiring**：新 AST/import 守卫——`memory`/`providers` 不被上层 import 具体实现、策略/surfaces/capabilities 视图无 `MemoryStorePort`/`VectorBackend` 裸句柄；带 `--self-test`（植入违规→判红）+ fail-on-empty；接入 CI `boundaries` 独立 blocking job（承 C15）。依赖 T14。验证：self-test 判红 + 全绿。commit：`test(ci): memory layering guard + self-test`。
- [ ] **T18 收尾活文档**：回填 `design/06-memory.md` §6 待定（chunk schema 定形、半衰期默认、covered_hash 生产者后置 P10 的诚实标注）、`design/04` §7 压缩↔记忆桥接缝、`design/01` §2/§13 `recovery_pointers` 形态；更新 `CHANGELOG.md` `[Unreleased]` Added — P4；`ROADMAP.md` §1(P4 状态)/§1.5；核对本文 §0 引用精度（避免 P3 审计 F1-F3 类 stale 行号）。commit：`docs(p4): plan/04 + living-docs + CHANGELOG`。

## 3. 契约与红线自检

- **触分层/契约？□是 → 先 ADR（T1–T4 已在任何代码前）**：分层定位(0023)/契约演进(0024)/蒸馏单写者(0025)/检索投影(0026)。
- **逐条 C1–C18**：C1/C14 记忆子系统包边界 + `lint-imports`/ruff banned-api/AST 三守卫（T17）；C2/C5/C13 写=`WriteMemory`→reduce、Event 不反哺、delta 不持久、记忆正文不进 `Domain_State`（T11）；C4 读写经 Harness 持有 `MemoryStorePort`、策略无裸句柄（T5/T10/T12/T17）；C6 外部事件**只新增可选 `memory_written`**、不改既有 type/关联键/终止序（T6，protocol diff 守）；C11 接缝先 ADR、字段 v0 后锁；C18 记忆写入/检索命中进 prompt/事件前 size cap + artifact + 字段级白名单（T4/T11/T12）；C16 surfaces 只 `submit`、不直 reduce（T14）。无违反，例外均已 ADR。
- **事件协议只增不改**：仅加 1 个可选外部 type + `data` 可选字段；`check_protocol_schema --self-test` 能判红；未知 type 静默忽略（error 类除外）。
- **快照版本兼容**：schema v2→v3（加 `covered_hash`）；`rebuild_run`/`from_snapshot` 未知版本 fail-closed + v2→v3 幂等迁移（复用 P3 `contract_version` 闸门，不重复造）。
- **与 P3 复用不重造**：`rebuild/after_seq/双游标 gseq/store schema 版本闸门/check_replay_determinism` 直接继承；`memory.db` 用同款"单一 `_SCHEMA` authority + 幂等 DDL + `BEGIN IMMEDIATE`"，但**独立库**（故障隔离）。

## 4. 测试与回归

- **单元**：`test_memory_store`（版本判红/损坏重建/独立库不拖垮 event_log）、`test_chunker`、`test_hybrid_fusion`（断非 RRF、rank-normalize）、`test_temporal_decay`、`test_deep_dream`（hash 去重 no-op/空哨兵/只删不编）、`test_recovery_pointer_covered_hash`（改写覆盖区→读回 fail-closed）、`test_snapshot_v3`。
- **集成**：`test_p4_memory_write_readback_cross_session`（DoD①）、`test_p4_deep_dream`（DoD②）、`test_p4_memory_single_writer`（DoD③）、`test_p4_memory_policy_pluggable`（DoD④，两策略 loop 零 diff）、`test_p4_durability`。
- **evals 任务级**：最小回归网——固定 fake provider 下"写一件事→新会话检索→蒸馏固化→再检索召回"端到端，为 P10 回归网打底。
- **守卫/冷导入**：全 `src/questor/**` 逐模块 `python -c "import <mod>"`（failimports=0）；`lint-imports` kept；`check_protocol_schema --check`；`check_layering_ast`/`check_memory_layering`/`check_output_budgets`/`check_secret_projection`/`check_replay_determinism`/`check_thread_leak`/`verify_p0` **各 `--self-test` 能判红**且 fail-on-empty；Windows 真机 leg。
- **诚实边界（UNVERIFIED，不用 fake 冒充）**：真 embedding provider（无 key）、真 LLM Deep Dream **质量**（结构/纪律可测，语义质量不测）、CJK trigram 真机效果、完整四档压缩调优（`disable_compaction=True`→P10）、`recovery_pointers` **生产者**（压缩触发→P10，P4 仅定形+fail-closed 读校验）。以上在交付报告逐项标注，不得伪装"实测通过"。

## 5. 落地风险 & 备选

| 风险 | 触发条件 | 缓解 | 备选 |
|---|---|---|---|
| 范围错配：为凑 DoD① 强启压缩 | 误以为"写入必须靠压缩丢弃触发" | DoD① 走**显式 `WriteMemory`** + run-完成 flush；压缩桥**只定接缝不接活路**（`disable_compaction=True` 不动） | 全量四档压缩进 P4 → 否（破分层、超范围、与 04 §7/P10 冲突） |
| 契约腐化：payload 裸 JsonObject / covered_hash 缺失后期破坏性改 | P10 落地压缩时大改快照/协议（P3 审计 E1 预警） | T2 ADR-0024 先锁 typed + 快照 v3 + covered_hash 定形 + fail-closed | 留裸 JsonObject、P10 再改 → 否（届时快照历史迁移=痛返工） |
| 第二写者错觉：Deep Dream 直写 store | 被误读成旁路 reduce | ADR-0025 明确"单写者只强加 Domain_State、memory 用 atomic+hash 自立纪律"；`test_p4_memory_single_writer` + AST 判红 | Deep Dream 同步塞进活 run loop → 否（阻塞、撕裂状态、破可插拔） |
| 大输出/embedding 拖垮长跑 | 检索命中原文/向量入 prompt 无上限 | ADR-0026 size cap + artifact + 字段级白名单（承 ADR-0019）；向量缺省降级不抛 | 命中全文直塞 prompt → 否（内存/SQLite/SSE 三爆，违 C18） |
| 记忆库损坏连带运行态 | event_log 与 memory 同库 | 独立 `memory.db`、故障隔离（R03 D-P1）；`test_p4_durability` 断隔离 | 复用同一 `StorePort`/同库 → 否（一处崩全崩） |
| L7 重编号破守卫 | 把 memory 当 L7 改层号 | ADR-0023：memory 为跨层子系统、不占层号 | 重编号 → 否（破 import-linter/ruff/AST） |
| 真机不可复现项被 fake 冒充 | 无 embedding/LLM key 环境 | 结构/纪律用 fake provider 测、语义质量标 UNVERIFIED | 伪造"真机通过" → 禁止 |

## 6. 收尾（活文档，AGENTS §5.5/§5.6）
- [ ] 回填 `design/06` §6 / `design/04` §7 桥 / `design/01` §2·§13 `recovery_pointers`（就地标注、历史不回改）
- [ ] `CHANGELOG.md` `[Unreleased]` Added — P4（含 provenance/许可注）
- [ ] `ROADMAP.md` §1(P4 状态)/§1.5 备注（若阶段顺序变→先 ADR，ROADMAP §5）
- [ ] 偏差回填 ADR-0023~0026；审计/验收证据文件**只追加/就地标注**
- [ ] §0 peer-scan `file:line` 精度终检（防 P3 审计 F 类 stale 引用）

---

## 7. 被否备选（Rejected Alternatives）
1. **记忆重编号为 L7**：与 `00-layering`/`STRUCTURE` 的 L7=Shell 冲突，破 import-linter/ruff/AST 三守卫的层号方向；记忆应作 `state/` 的 peer 子系统（`src/questor/memory/`），跨 L0/L2/L4/L5。**否**。
2. **复用 P3 event-log `StorePort`/同库承载记忆表**：违故障隔离（R03 D-P1），一处损坏拖垮运行态；且语义混淆"事件溯源 log"与"知识层"。**否**，改独立 `MemoryStorePort`+`memory.db`。
3. **记忆正文进 `Domain_State`**：破 state/memory 分离（DoD⑤）、撑爆快照、污染回放。**否**，只可有界检索投影经白名单。
4. **Deep Dream 同步跑在活 run loop**：阻塞热路径、可插拔性丧失、有撕裂状态风险。**否**，离线批 + run-边界异步 flush。
5. **RRF 融合**：design/06 §2 明确 rank-normalize 加权、非 RRF。**否**。
6. **逐行移植 hermes `MemoryProvider` / Cow `manager` / 搬 EvoFlow `evopanel` 码**：许可边界（evopanel PolyForm Noncommercial 禁进 MIT 项目）+ 与 Questor 契约（Command→reduce→StorePort）不兼容。**否**，仅改造思路 + 标 provenance。
7. **P4 强启四档压缩以产 `recovery_pointers` 数据**：与 `disable_compaction=True`(P10) 冲突、超范围。**否**，covered_hash 先定形、生产者后置。
8. **现在就上跨进程记忆一致性/分布式索引**：单机 SQLite+atomic+hash 足够（C12/天花板）。**否**，后置。

## 8. 依赖图（关键路径）
```
T0 基线/worktree
 └─ T1 T2 T3 T4  (ADR-0023~0026)  ──▶ T5 contracts/memory (L0 数据+端口)
        └─▶ T6 events/ports/policy/state_schema 接线
              ├─▶ T7 snapshot v3 + covered_hash fail-closed (L1)
              └─▶ T8 store_memory_sqlite (L5, memory.db)
                     ├─▶ T9 chunker/sync ─▶ T10 检索栈(pluggable)
                     │                          └─▶ T12 memory_search(L3)
                     │                                └─▶ T15 policy 记忆策略(L4)
                     └─▶ T11 reduce WriteMemory ──┬─▶ T13 Deep Dream+flush
                                                    └─▶ T14 surfaces 装配/组合根
                          T12/T13/T14/T15 ─▶ T16 测试/evals ─▶ T17 守卫+CI ─▶ T18 收尾
```
**关键路径**：`T1–T4 → T5 → T6 → T8 → T10 → T11 → T12 → T14 → T16 → T17 → T18`（DoD①/③ 依赖链）。T7/T9/T13/T15 可并行支线。

## 9. 本阶段与既有文档不一致处 —— "全局最优"裁定清单
1. **"记忆属 L7"（用户口径） vs L7=Shell（00-layering/STRUCTURE §6） vs memory 落 `src/questor/memory/`（STRUCTURE §9）** → 裁定：记忆**非新编号层**，是与 `state/` 分离、跨 L0/L2/L4/L5 的**独立子系统包**；"L7"读作"独立子系统"，不改层号（否则破三守卫）。→ ADR-0023。
2. **C4 字面"读经 StorePort" vs design/06 §4"StorePort 同款切" + P3 的 StorePort 是 event-log 语义** → 裁定：新增独立 `MemoryStorePort`/`VectorBackend`，仍是 **Harness 持有接口**、满足 C4"无裸句柄"意图；命名以 ADR 固化，避免误读为旁路。
3. **Deep Dream 直写 vs 单写者 C2** → 裁定：C2 单写者**只强加 `Domain_State`**；memory store 是独立持久子系统，用**文件真源 + atomic + 输入 hash + claim-then-commit** 自立纪律，不触 `Domain_State`，故非第二写者。→ ADR-0025。
4. **DoD① 写入触发源**：design/06 §1"short→long 由压缩丢弃驱动"与 `disable_compaction=True`(P10) 冲突 → 裁定：P4 的 daily 生产者 = **显式 `WriteMemory`** + **run-完成边界 flush**（hermes `commit_session_boundary_async`）；压缩丢弃→MemoryWrite 的 L2' 桥**只定义接缝、活路后置 P10**。
5. **`recovery_pointers` covered_hash（P3 审计 A2/E1 后置 P4/P10）** → 裁定：P4 **定形 typed 三元 + 快照 v3 + fail-closed 读校验**（防后期破坏性改 schema）；**生产者**（压缩触发写指针/锚哈希）随压缩后置 P10。快照 v2→v3 属 additive + 版本闸门、非破坏。
6. **外部事件新增 `memory_written`（协议 19→20）** → 裁定：属 C6 允许的"只增可选 type"，`check_protocol_schema` 只增不破；记忆原文**不进外部事件**、仅 bounded 引用。
7. **进入条件"P3 已完成"** → 事实：P3 经 PR #21（merge commit `4ab9d91`）**已合入 `main`**。裁定（诚实）：P4 实现开工基线 = **最新 main**；`recovery_pointers` CoveredHash 生产者与 `driver_id/driver_version` 仍按 P3 审计显式后置 P4/P9/P10，不由 P3 承担。

## 10. 执行约定（实现阶段开工基线；本规划只落文档、不改代码）
- **隔离 worktree**：因本仓 **PR-only + 并发多窗口**（ADR-0012 B 案；"多窗口切分支导致提交落错分支"教训），实现**必须**用**独立 git worktree** 承载 `feat/p4-memory-soul`，禁止在主工作区切分支。
- **基线**：`feat/p4-memory-soul` 从含 P3 的最新 main（`4ab9d91`）切（见 §9 裁定 7）；切前先复跑全质量门取 GO（T0）。
- **细粒度提交**：按 §2 每 commit 一个原子动作、英文 Conventional Commits（`feat/fix/test/docs(adr|contracts|state|memory|providers|capabilities|policy|surfaces|ci)`）；**不伪造时间戳/作者**；**commit/push 前每步须经用户明确 in-turn 许可**（AGENTS §6）。
- **安全评审**：push / 开 PR 前按流程走 **L3 深度安全评审**（记忆涉及跨会话数据落库/检索投影，重点审 C4/C18 裸句柄与白名单外泄、`memory.db` 注入/路径逃逸、Deep Dream 只删不编）；CI `boundaries` 独立 blocking job 为真门禁。
- **DoD 验收**：收尾以**可复现行为 + 真机测试**为准，不可复现项诚实标 UNVERIFIED、不用 fake 冒充真机/真模型；审计/验收证据文件只追加/就地标注、历史不回改。
- **本会话限制**：`Agent` 子代理被禁用，三视角规划由编排者顺序自行完成（非独立多代理评审）；实现阶段应按能力**重新派发** `Search`/`CodeReview` 独立复核。

## 11. 实现偏差回填（T0–T18 交付后，2026-10-16）
- **进入条件更新**：P3 经 PR #21（merge commit `4ab9d91`）已合入 main；P4 从含 P3 的最新 main 切 `feat/p4-memory-soul`（隔离 worktree，detached→branch）。
- **T17 实现方式修正（全局最优）**：未新建 `scripts/check_memory_layering.py`，而是**扩现有** `check_layering_ast.py`（加 memory 层 rank + `policy`/`surfaces`/`capabilities` 禁 import 具体 `store_memory_sqlite`），复用其 `--self-test`/fail-on-empty 引擎、且已在 CI `boundaries` blocking job 运行——避免重复 AST 走子、CI 覆盖自动。DoD③ 静态守卫等价达成。
- **T15 口径修正（与 DoD④ 一致）**：`DefaultTurnLoop._ask_policy` 构造 `PolicyView` 时**不**自动填充 `view.memory`（否则把记忆检索耦合进 L2、违"换策略不动 loop"）。DoD④ 主证据由可插拔 `MemoryStrategyConfig`（T10）+ `memory_search` 工具（T12）承载；`MemoryAwareReActPolicy` 是 L4 消费 `view.memory` 的接缝示例。
- **DoD① 的 daily 生产者**：按 ADR-0025 用显式 `WriteMemory` + run-完成 flush（不强启被后置 P10 的压缩），使 DoD② 有真实可测输入。
- **covered_hash / 压缩**：typed `RecoveryPointer` + 快照 v3 + fail-closed 读校验已在 P4 定形；写锚**生产者**与四档压缩调优诚实后置 P10（`disable_compaction=True` 未动）。
- **UNVERIFIED（未 fake）**：真 LLM Deep Dream 语义质量、真 embedding 召回质量、跨进程记忆 exactly-once（→P9）。**trigram-CJK 未实现→后置 P10**（属"未实现"，非 UNVERIFIED）。
- **交付质量门**：412 passed / 5 skipped；ruff clean、lint-imports 4 kept、AST 76 files/0 违规（含记忆规则 self-test 判红）、protocol 20 types lockstep、verify_p0 ALL PASS。ADR-0023~0026 与代码均按细粒度提交（逐任务/逐文件绿）。

## 12. 对抗审计修复轮（`docs/audit/P4-review-2026-10-16.md` CONDITIONAL GO → 闭合）
- **§6-1 写生产者**：`CliSurface.run_once` run 完成边界 best-effort 调 `flush_run_to_daily`（经 `MemoryStorePort`、不进热 loop、`run_id` 幂等、失败仅告警）；`test_p4_memory_flush.py` 走真实 loop 证写→检索（非手动 inbox）。
- **§6-2/§4-B trigram**：代码只两档→ ADR-0026/design-06/plan §0/CHANGELOG/`store:13` 全部改口径为"两档 + trigram-CJK 未实现→后置 P10"。
- **§6-3 重试**：`_call_distill` 有界重试 transient、耗尽上抛（不静默吞），配测试。
- **§6-4 D③命名测试**：新增 `test_p4_memory_single_writer.py`。
- **§6-6 source**：`memory_written.source` 用真实 `MemorySource`（`contracts.memory.source_for_write`）。
- **§6-5 `PolicyView.memory` 生产者 backlog**：loop 有意不自动填充 `view.memory`（以免耦合 L2、DoD④）——**归属记 P5/P7 backlog**：若将来做"检索自动注入 prompt"，由一个 harness 侧只读分支预取器填入有界投影，而非写死进 `DefaultTurnLoop`。在此之前 `MemoryAwareReActPolicy` 是消费 `view.memory` 的待定接缝示例（生产路径 `view.memory` 为空）。

## 13. 全链路复查（记忆之外；2026-10-16）
实跑了 `python -m questor`（REPL→run→flush→daily→`--dream`→core）、`--list`、`--resume`、全守卫 self-test + fail-on-empty、冷导入、静态扇。新发现：
- **[已修] `--dream` heuristic 蒸馏器只喂 daily → 每次重写 core 会丢更早的既有精华**。修：`_HeuristicDistiller` 合并"现有 core + 近期 daily"（单调不回退），`test_heuristic_distiller.py` 钉住。
- **[P7 backlog] HTTP/SSE 面（`EventServer`）绕开 `run_once`/`resume` 直接 `surface._loop(...).drive` → 不触发 run-完成 flush、无 `POST /runs/{id}/memory` 写路由**。P4 组合根只起 CLI、未起 HTTP（`create_app` 仅测试用），故非 P4 live bug；但 P7 sidecar 起 HTTP 时必须镜像 CLI 的 flush + 经 inbox 的 `WriteMemory` 路由（否则 HTTP 驱动的记忆只有读侧）。
- **[语义说明] run-完成 flush 沉淀的是"最终 assistant 回答"、非用户"记住 X"原话**（episodic = agent 产出）。逐字记住需 P5 显式 `WriteMemory` 路由（当前唯一生产写者是自动 flush）。
- **[非 P4、仅记录] `cli.py` 顶层 import `LiteLLMProvider` → 每次 import CLI 触发一次 litellm cost-map 网络抓取（超时回落本地）**：P1 既有，可延迟 import 后置清理。
