# ADR-0055: 自动召回默认开（生产）+ citation 协议块解析即剥

- 状态：✅（2026-10-21，B8；`[behavior]` = 组合根翻默认）
- supersedes：`optimize-scan/QUESTOR-OPTIMIZATION-PLAN.md` OPT-12(b) 的"注入位存在但默认关"口径
  （那是接缝交付口径；§20.6 早已写明**翻转默认是 v3 的责任**，本 ADR 就是那次翻转）
- 背景：OPT-12(b) 只给了"记忆注入位、默认关、行为字节不变"。§6.2/§6.3 要求的是**能用**：
  三通道召回 + 小模型终选 + "消费可归因（引用而非注入计数）"。同时 `AssembleSpec`/`CliSurface`
  的既有默认与逐字节金标（`test_assemble_spec_default`、`test_context_assembler_golden`）不许动（R3）。
- 决策：
  1. **内核只依赖端口**：新增 `contracts/memory.RecallPort`；召回实现（三通道 + 三门控 + 终选）住在
     `memory/recall.py`。kernel 不 import `memory/`、不持 store 裸句柄（C1/C4）。
  2. **档2 只进请求、不进事实流**：召回块作 user-role 前缀消息拼进 `ProviderRequest.messages`，
     **不写进 Domain_State**——召回是"本轮模型看到什么"，不是"发生了什么"（C5）；进事实流会污染
     重放与缓存前缀。正文**永不进 system**（§6.1 分档）。
  3. **三门控**：triviality（`is_trivial`）、可跳过（`SubmitMessage.flags.skip_recall`，谓词
     `recall_skipped_by_flags` 唯一一份，L0）、可归因（无 `entry_ids` 就不注入）。
  4. **引用即剥**：模型按协议块 `<citation_entries>{...}</citation_entries>` 自报；harness 在
     `_stream_turn` 里解析 → 从正文剥掉 → 随 `AppendAssistantMessage(citations=...)` 交给 reduce
     挂到 `message_completed.citations`。剥完的正文才进 context，因此**下一轮请求体不含协议块**。
  5. **命中 ≠ 消费**：`memory_search` 命中**不发** `memory_consumed`；只有 ①被 citation 引用、
     ②`read` 工具真读了记忆根下的文件 才发，且条目级 `entry_id=path:start-end`；识别不了直接不计数。
  6. **默认翻转只在组合根**：`build_app()` 构造 `MemoryRecall(enabled=True)` 注入 surface；
     直接 `CliSurface(...)` 与 `MemoryRecall(...)` 的默认仍是关。
  7. **向量单库**：`EmbeddingPort` 只产向量；embedding 落**同一** `memory_chunks.embedding` 列，
     不建第二 store/第二索引表（§20 C-3）。CI 无密钥用 `FakeEmbedder`（确定性、可重放）。
- 后果：
  - 正面：召回真的能用了；注入可归因（`memory_injected` 带 kind/entry_ids）；§10 的"写入噪声率"
    有条目级数据可算；provider 请求体不被协议块污染。
  - 代价：生产请求体每轮多一段召回正文与一次检索（有上限 5 条 + snippet 字节界）；真检索质量与
    真 embedding 效果 **UNVERIFIED**（fake 只证通道接得通）。
  - 需持续守：任何"把召回正文塞进 system"的改动都违反 §6.1 分档，必须先改本 ADR；
    `memory_consumed` 不得由搜索命中产生，否则写入噪声率会被虚假清零（§6.3 硬规定）。
- 备选（被否）：
  1. **注入计数当消费**（v2 §4.7 门 2）：否——§6.3 已推翻，"注入型召回"会自证其美。
  2. **文件级引用**：否——分不清"读了哪段"，条目级指标算不出来。
  3. **建 `memory_history` 表记引用**：否——§20 C-7 已定"变更史=事实流"，引用同理走事件流投影。
  4. **在 surface 里做召回**：否——只有内核知道"本轮要发什么请求"，且 surface 零业务（S6）。
  5. **翻转放在 `CliSurface` 默认值**：否——会让既有直连构造（含若干回归测试）的行为一起变，
     且与 §20.6"翻转带行为变更门、发生在生产入口"的口径不符。
- 关联：v3 §6.1/§6.2/§6.3、§13 B8、§20.3 C-3、§20.6；`docs/adr/0054-*`（档1 索引）、
  `contracts/memory.py`、`memory/recall.py`、`kernel/loop.py`、`state/reduce.py`、
  `surfaces/cli.py`、`composition.py`；`tests/unit/test_memory_recall.py`、
  `tests/unit/test_memory_citation.py`、`tests/unit/test_recall_consumption.py`。
