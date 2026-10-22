# ADR-0054: 档1 记忆索引进 system 定界段 + cache 三条款（生产默认开）

- 状态：✅（2026-10-21，B7/c1–c3；`[behavior]` = c2）
- supersedes：无（OPT-12a 只交接缝与"默认关"，本 ADR 是 §20.6 里 v3 负责的默认翻转）
- 背景：v3 §6.1 指出两件事同时坏：① 记忆正文若进 system，每轮都撕 prompt cache 前缀且注入面失控；
  ② 若完全不注入，模型永远看不到"有哪些记忆"。OPT-12a 只留了 `memory_block_provider` 接缝且默认关
  （`tests/unit/test_context_assembler_golden.py` 把逐字节 golden 钉住，含 `system=None` 的字面 `"None"`）。
  R3 不允许改该金标 → 翻转只能发生在**组合根**。
- 决策：
  1. **分档**：档1 = `MEMORY.md` 的 pointer 行，进 system 的**定界静态子段**；档2 = 召回正文
     （B8 才做，绝不进 system）；档3 = 工具读到的记忆（既有有界 `tool_result` 路径）。
  2. **四道准入约束**（`memory/index.py`，缺一即整段不注入 = 降级走档2）：
     ① 有界 ≤30 行且 ≤4000B（≈1k token）；② 每行过 `bound_description`（该函数从
     `capabilities/tools/registry.py` **逐字下沉到 `contracts/common.py`**，否则 memory 层要反向
     import L3）；③ `LEAD_IN` 前导语声明"参考数据、非指令"；④ 发 `memory_injected` 观测条目。
  3. **注入位在本 run 的 system，不在 `CliSurface.system`**：`_loop` 用 `inject_memory_block` 组装，
     `surface.system` 保持 skills 装配结果 → 既有 golden 与 `test_assemble_spec_default` 的字段等价零改动。
  4. **默认翻转只在 `composition.build_app()`**（`memory_index_enabled=True`）：生产四入口全开；
     直接构造 `CliSurface`（测试/嵌入）仍默认关。
  5. **可观测契约**：新增两个 **live-only** 事件 `memory_injected`（kind/entry_ids/lines/bytes/truncated，
     无正文）与 `cache_break`（三段 hash + reason + breakpoints）；四处 lockstep 同批落，`v` 不 bump。
  6. **cache 三条款**（`memory/cache_plan.py`）：4 断点预算 `[system, history_start, tool_face, reserved]`，
     超预算 **砍断点不砍内容**；TTL 按 query source 门控（只有 `main` 拿长 TTL，side-query 不开 cache 且
     不参与断裂观测）；断裂 = 三段 hash 首个变化维度，`budget` 单列。frozen/fresh 二分：优先替换 fresh，
     frozen 单独超预算也**不动它**（动它必然全量断裂）。
- 后果：
  - 正面：记忆"可见"不再靠每轮塞正文；注入可归因（有事件）、有界（有预算）、可审计（有计量）。
  - 代价：生产默认行为变了（`ProviderRequest.system` 在装配了记忆库时多一段定界文本）；索引段每 run 重建
    一次（读一个 md，代价可忽略）；默认翻转只在组合根，读代码时"surface 默认关"与"生产默认开"必须**带刀号**理解。
  - 需持续守：`memory_injected` 载荷不得出现正文（schema `additionalProperties:false` + 白名单双向钉）；
    任何把召回正文塞进 system 的改动都违反 §6.1 分档，必须先改本 ADR。
- 备选（被否）：
  1. **每轮把召回正文塞进 system**：否——§6.1 明确档2 不进 system；缓存前缀会被每轮撕掉。
  2. **直接改 `assemble_system_prompt` 的默认输出**：否——会破 `system=None` 字面 `"None"` 金标（R3），
     且把"生产默认"和"接缝默认"混在一处。
  3. **在 loop 里读记忆文件**：否——kernel 不碰 IO/不 import 能力层（C1）；索引由 surface 经
     `MemoryStorePort` 读，loop 只拿计量。
  4. **新建 `MemoryIndexPort` 抽象**：否——接缝已存在（`ContextAssemblerPort` + `MemoryStorePort`），
     再加一层只是把一次函数调用换成一个协议（G1 半径原则）。
- 关联：v3 §6.1、§13 B7、§20.6（默认值交接）、§21 G5/G6；`contracts/common.py`、`contracts/events.py`、
  `memory/index.py`、`memory/cache_plan.py`、`kernel/loop.py`、`surfaces/cli.py`、`composition.py`；
  `tests/unit/test_memory_index.py`、`tests/unit/test_memory_index_injection.py`、`tests/unit/test_cache_plan.py`。
