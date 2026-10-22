# ADR-0051: 工具 reader/writer gate + 真并发派发——从 P10 悬置再次收口为独立并行化 Phase（post-P10）

- 状态：✅（2026-10-19，P10 开工前置门；收口 [`ADR-0039`](./0039-parallel-gate-attribution-recut.md) 决策 ② 遗留的"P10 或独立 Phase"悬置）
- 背景：[`ADR-0029`](./0029-parallel-tools-deferred-beyond-p5.md) 把 `parallel_safe`/`barrier` 移出 P5、推迟"专门并行化 Phase"；[`ADR-0039`](./0039-parallel-gate-attribution-recut.md) 决策 ② 明确把**工具 reader/writer gate + 真并发派发**"显式再推后一次，归口 P10 **或** 独立并行化 Phase"。[`../design/HARD-CONSTRAINTS.md`](../design/HARD-CONSTRAINTS.md) C19:108 "不是并行通行证……工具 gate → 专门并行化 Phase（P10 或独立）"。P10 计划裁决点须终结"P10 或独立"的模糊——否则正重演 ADR-0039 立项要消灭的"注释说 P#、其实没人做"隐债。现场核：`contracts/tool.py` `parallel_safe`/`barrier` 字段仍存（契约不删、不破 C6/C11），全仓无读它们改变派发的代码——执行严格串行（[`ADR-0028`](./0028-pairing-gate-and-provider-fault-normalization.md)/C19 回发前配对关卡）。
- 决策：
  1. **工具 reader/writer gate + 真并发派发不在 P10 落地**，**再次显式收口为"独立并行化 Phase（post-P10，尚未立项）"**，从 P10 范围摘出。**理由**：① P10 已承载三个较独立子系统（压缩/观测刀3/eval 网），叠加"改动 turn 循环派发模型（串行→并发）"是最高 blast radius（ADR-0039 被否选项 1 原语）；② 其设计输入（真并发 × `concurrency_safe`/capability floor 矩阵）尚未具体化，提前定形易返工（C11）；③ 它不服务任何 P10 DoD。
  2. **同步收口措辞（消隐债，随本 ADR 落地，不回改 ADR-0029/0039 正文）**：把 [`HARD-CONSTRAINTS.md`](../design/HARD-CONSTRAINTS.md) C19 与 [`ADR-0039`](./0039-parallel-gate-attribution-recut.md) 决策 ② 中"P10 或独立 Phase"统一改判为"**独立并行化 Phase（post-P10，未立项）**"。属 ROADMAP §5"功能跨阶段移动"——**先有此 ADR，才动 HARD/plan 文案**。
  3. **持续不变式**：本 Phase 与既有实现仍**不读** `parallel_safe`/`barrier` 改派发，执行严格串行 + 回发前配对（C19/ADR-0028）；[`ADR-0041`](./0041-fanout-budget-and-runaway-control.md) 落地的**子代理 fan-out admission gate**（run 级、`SubagentSpawnerPort` 强制）与本条正交、不受影响。字段留 `ToolSpec` 但 gate 落地前任何执行路径不得据其并发派发（既有串行实现 + ADR-0028 调用点唯一守卫兜底）。
- 后果：正面——ADR-0029/0039 三轮悬置的"暂定归口"就此钉死一个新家（独立 Phase）与被明确宣告"仍未做"，账不再飘；C19 串行配对不变式在 P10 全程完好。代价——工具并行的债再被点名挂一次（本 ADR 即那一次，绝不允许"悄悄没人做"）；若真并发需求急迫，须单立并行化 ADR + Phase。
- 备选（被否）：
  1. 纳入 P10 落工具 reader/writer gate + 真并发派发：把派发模型改造叠进三子系统同 Phase 的 blast radius，违 ADR-0029/0039 反对的高危叠加，且 P10 DoD 不需要 → 否。
  2. 继续留"P10 或独立"模糊措辞不裁决：正是本 ADR 要消灭的"注释说 P# 其实没人做"隐债 → 否。
  3. 现在就设计 gate 形状并落字段读点：设计输入未具体化、易返工（C11）→ 否。
- 关联：[`ADR-0028`](./0028-pairing-gate-and-provider-fault-normalization.md)/[`ADR-0029`](./0029-parallel-tools-deferred-beyond-p5.md)/[`ADR-0039`](./0039-parallel-gate-attribution-recut.md)/[`ADR-0041`](./0041-fanout-budget-and-runaway-control.md)；[`../design/HARD-CONSTRAINTS.md`](../design/HARD-CONSTRAINTS.md) C11/C19；`contracts/tool.py`；`docs/ROADMAP.md` §1.5/§2.5；`docs/plan/10-p10-hardening.md` §2/矛盾裁决 5。
