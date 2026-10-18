# ADR-0039: 并行 gate 归口再决——P8 只落"子代理 fan-out gate"，工具 reader/writer gate 后置

- 状态：✅（2026-10-18，P8 开工前置门；收口 [ADR-0029](./0029-parallel-tools-deferred-beyond-p5.md) 的"暂定归口"悬置）
- 背景：[ADR-0029](./0029-parallel-tools-deferred-beyond-p5.md) 把 `parallel_safe`/`barrier` 移出 P5、推迟到"专门的并行化 Phase（暂定归口 P8 或独立立项）"，且其 `:15` 明确**区分**了两类"P8"——① orchestrator/子代理 gate（`contracts/tool.py` 的"until P8"，真属 P8）与② 工具 reader/writer gate（同 run 内 `tool_use` 真并发派发，属并行化 gate）。ADR-0029 `:30-31` 还说"并行 gate 的设计输入（多工具真并发、subagent fan-out）要到 P8 才具体化"。**若不在 P8 显式收口，就重演 ADR-0029 立项要消灭的"注释说 P#、其实没人做"隐债。**
- 决策：
  - **① 子代理 fan-out admission gate → P8 落**：`capabilities/subagent` 的 spawn 处，用 wuu `spawn_slot.go` 式 reservation（`running+pending >= max_parallel_children` 即拒、防 TOCTOU 超发）+ `max_tree_depth` 判定。它是 **run 级并发准入**（多个 `RunController` 在 asyncio 上并发），与"同 run 内多 `tool_use` 并发派发"正交。详见 [ADR-0041](./0041-fanout-budget-and-runaway-control.md)。
  - **② 工具 reader/writer gate + 真并发派发 → 显式再推后一次**，归口 **P10 或独立并行化 Phase**（届时按 capability + 远程 `concurrency_safe` hint 的 capability floor 一起设计，参照 ADR-0029 引的 DeepCode `core/mcp/tools.py:77-78`：`concurrency_safe` 只是 per-server hint、非授权）。P8 **不实现**、**不读取** `parallel_safe`/`barrier` 改变派发——执行仍严格串行 + 回发前配对（[ADR-0028](./0028-pairing-gate-and-provider-fault-normalization.md)/HARD C19）不变。
  - **口径同步（消隐债，随本 ADR 落地）**：把 `HARD C19`（`:108`）、`ADR-0029` 的"暂定归口 P8"、`docs/plan/05` T13 的相关措辞统一收敛为"子代理 fan-out gate 落 P8（ADR-0039/0041）；工具 reader/writer gate → dedicated parallelization phase（P10 或独立）"。**不回改 ADR-0029 正文**，在此登记取代/收口关系。属 ROADMAP §5"功能跨阶段移动"——**先有此 ADR，才动 HARD/plan 文案**。
- 后果：
  - 正面：ADR-0029 留下的"暂定"不再悬空——一类 gate 在 P8 真落、另一类有明确新家与新判据；P8 的并发只在 run 级、不触碰最易自伤的 C19 串行配对面。
  - 代价/需持续守：工具并行 gate 的账再记一次（本 ADR 即那一次，绝不"悄悄没人做"）；`parallel_safe`/`barrier` 字段仍留 `ToolSpec`（契约不删、不破 C6/C11），但其 gate 落地前任何执行路径不得读取它们改变派发（既有串行实现 + ADR-0028 调用点唯一守卫兜）。
- 备选（被否）：
  1. **P8 同时接工具 reader/writer gate**：把"改动 turn 循环派发模型（串行→并发）"与"新编排子系统"叠进同一 blast radius——正是 ADR-0029 反对的高危叠加，且 DoD"两 agent 协作"不需要工具级并发 → 否。
  2. **另立刻立独立并行化 Phase 并在此就设计 gate 形状**：工具 gate 的设计输入（真并发 + capability floor 矩阵）尚未在具体化，提前定形易返工（C11）→ 否，留待 P10/独立 Phase。
  3. **只字不提、任其散落**：重演"字段存在≠gate 存在"隐债 → 否。
- 关联：[ADR-0029](./0029-parallel-tools-deferred-beyond-p5.md)（本 ADR 收口其归口）、[ADR-0028](./0028-pairing-gate-and-provider-fault-normalization.md)、[ADR-0041](./0041-fanout-budget-and-runaway-control.md)；HARD-CONSTRAINTS C11/C19；`contracts/tool.py`；`docs/ROADMAP.md` §1.5/§2.5；`docs/plan/08-p8-multi-agent-dag.md` T6。
