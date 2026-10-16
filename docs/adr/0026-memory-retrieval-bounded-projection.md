# ADR-0026: 混合检索栈（rank-normalize 融合 + 时间衰减 + 降级）与有界投影

- 状态：✅（2026-10-16，决策定；实现见 [`../plan/04-memory-soul.md`](../plan/04-memory-soul.md) T10、T12）
- 背景：[`../design/06-memory.md`](../design/06-memory.md) §2 已定检索栈 = `向量(cosine) + 关键词(FTS5 unicode61 / trigram-CJK / LIKE 兜底) → rank-normalize 加权融合 → 时间衰减 → 可选 rerank → 命中热度 boost(默认关)`，且明确"**融合用 rank 归一(0,1] 加权，不是 RRF**；向量失败静默降级关键词，不抛"。检索命中原文将进入 prompt/下一轮上下文，受 HARD C18/ADR-0019"载荷有界 + 字段级白名单投影"约束。实扒：CowAgent `agent/memory/manager.py:742-799`（`_merge_results`）/`:722-740`（`_rank_normalize`）/`:657-697`（`_compute_temporal_decay` half_life 30d、core 常绿）/`:181-201`（无 embedding 静默降级）、`storage.py:898-1010`（三档关键词降级 + BM25）。
- 决策：
  - **融合算法 = rank-normalize 到 (0,1]、仅对命中通道加权平均**，**非 RRF**（承 design/06 §2、Cow `manager.py:742`）；权重归一防 NaN/负值（`manager.py:699-720`）。
  - **关键词三档降级**：FTS5 unicode61(纯 ASCII) → trigram FTS5(CJK/混合) → LIKE 兜底，BM25 排序（承 `storage.py:898-1010`）。
  - **向量后端不可用/无 embedding 时静默降级关键词-only、绝不抛**（承 `manager.py:181-201`）——使无 `LITELLM`/embedding key 的 CI 环境仍能跑通 DoD①（诚实标 UNVERIFIED 的只是真 embedding 的召回质量，非机制）。
  - **时间衰减**：仅对带日期 daily 文件指数半衰（默认 `half_life=30d`、配置化），core 常绿不衰减；**rerank / 命中热度 boost 默认关、后置**。
  - **有界与投影（HARD C18/ADR-0019）**：检索命中原文进入 prompt/事件前须**字段级白名单 + size cap + 超阈走 artifact 引用**；对外只回 `(path, start_line, end_line, score, snippet)` 有界片段，`snippet` 定长上限、内部绝对路径/env 不外泄；`memory_written` 事件仅 bounded 引用（无原文）。
  - **可插拔（DoD④）**：融合权重 / 半衰期 / rerank 开关经 `MemoryStrategyPort`（或配置）暴露，替换检索策略**不动 kernel**。
- 后果：正面——召回质量与长跑内存/SQLite/prompt/SSE 有界性兼顾；无 embedding 环境仍可复现 DoD①；策略可 A/B 调权不触内核。代价——CJK trigram 真机效果、向量+rerank 召回质量需真 embedding 才能验（标 UNVERIFIED）；artifact GC/session 清理后置 P10。
- 备选（被否）：
  1. RRF 融合：与 design/06 §2 定案直接冲突 → 否。
  2. 命中全文直塞 prompt：违 HARD C18/ADR-0019，长跑内存/SQLite/SSE 三爆 → 否。
  3. 向量失败即抛错中断检索：无 embedding 环境 DoD 不可复现、脆弱 → 否（须降级）。
  4. 融合权重/半衰期硬编码进 kernel：破"可插拔不耦合 Kernel"（DoD④）→ 否。
- 关联：[`../design/06-memory.md`](../design/06-memory.md) §1/§2/§4；[`../design/02-event-protocol.md`](../design/02-event-protocol.md) §2/§10；HARD-CONSTRAINTS C6/C18；ADR-0019/0023/0024；R06 §2.2/§4.3。
