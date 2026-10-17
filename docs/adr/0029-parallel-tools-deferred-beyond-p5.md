# ADR-0029: `parallel_safe`/`barrier` 从 P5 移出、推迟到专门的并行化 Phase

- 状态：✅（2026-10-17）
- 背景：`contracts/tool.py:54,57` 把 `parallel_safe` / `barrier` 注释为「NOT enforced until P5」，
  `docs/ROADMAP.md:35`（§1.5）与 `:48`（§2.5）也把「完整并行」列为「后置 P5」，`HARD C19`（`:108`）与
  ADR-0028（`:72`）同样写「reader/writer gate 与真并发属 P5」。但 P5 的 DoD（`docs/plan/05-p5-skills-mcp.md §1.2`）
  是「丢一个 `SKILL.md` 即生效 + 挂一个 MCP server 出工具」，**没有一条要求并行执行**。把并行 gate 塞进 P5，
  会把「新引入一个进程外错误源（MCP）」与「改动 turn 循环的执行派发模型（串行→并发）」两条高危变更叠进
  同一个 blast radius——而串行派发 + 回发前配对关卡（`kernel/loop.py` 的 `_execute_tool` / `_ensure_paired_history`，
  ADR-0028）正是 C19 最易自伤的面。留成「注释说 P5、路线图说 P5、其实没人做」就是隐债。
- 决策：
  1. **`parallel_safe` / `barrier` 移出 P5**，推迟到一个**专门的并行化 Phase**（暂定归口 P8 编排期一并落 reader/writer gate，或独立立项）；P5 全程**执行严格串行**。
  2. P5 内**同步改口径消隐债**（`docs/plan/05-p5-skills-mcp.md` T13）：把 `contracts/tool.py` 的「until P5」注释、
     `HARD C19`、`ROADMAP §1.5/§2.5`、ADR-0028 措辞统一改为「deferred beyond P5 → dedicated parallelization phase」；
     `orchestrator` 的「until P8」保留不动（那是子代理 gate，不属本决策）。
  3. 本 ADR 是 ROADMAP §5「功能跨阶段移动 → 先记 ADR 再改路线图」的前置门：**先有此 ADR，才动 §1.5/§2.5 文案**。
- 后果：
  - 正面：P5 只需守「发出前成对 + 串行」这一条已验证的不变式（ADR-0028），风险面收窄；并行 gate 作为独立子系统，
    要连同「按工具 capability + 远程 `concurrency_safe` hint 的 capability floor」一起设计（参照 DeepCode
    `core/mcp/tools.py:77-78`：`concurrency_safe` 只是 per-server hint，非授权），一次做对比拆两处半成品强。
  - 代价/需持续守：字段 `parallel_safe`/`barrier` 仍存在于 `ToolSpec`（契约不删、不破 C6/C11），但**在其 gate 落地前，
    任何执行路径都不得读取它们改变派发**；这条靠「执行严格串行」的既有实现与 ADR-0028 的调用点唯一守卫兜。
  - 不改变 ADR-0028 的既有结论：其「完整并行 gate 仍归 P5」一句随本 ADR 修正为「归专门并行化 Phase」，
    属 ROADMAP §5 允许的阶段内功能移动，不回改 ADR-0028 正文、在此登记取代关系。
- 备选（被否）：
  1. **在 P5 一并实现完整并行**：否——超出 P5 DoD，违 AGENTS §2 Simplicity First；且与 MCP 断连的 C19 配对回填
     （`plan/05` T5）叠加，两条高危同 Phase 改动显著提高自伤概率（`plan/05 §2.0` 理由 2）。
  2. **只改注释、不改路线图/ADR**：否——ROADMAP 与 HARD-CONSTRAINTS 仍写「后置 P5」，与实现长期不一致就是腐化源
     （AGENTS §5.5「Code merged, docs stale = not done」）。
  3. **现在就立项并行化 Phase**：否——并行 gate 的设计输入（多工具真并发、subagent fan-out）要到 P8 才具体化；
     提前定 gate 形状容易返工（C11「接缝早锁、字段后锁」）。先移出 P5、标注归口，P8 前再正式立项。
- 关联：HARD-CONSTRAINTS **C19**（串行派发 + 回发前配对不因本决策放宽）、C11、C6；ADR-0028（本 ADR 修正其「并行归 P5」一句）；
  `docs/plan/05-p5-skills-mcp.md`（§2.0 裁决 + §2 T13）；`contracts/tool.py`；`docs/ROADMAP.md` §1.5/§2.5。
