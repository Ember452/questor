# ADR-0004: 状态变更模型 — 单写者 + Command/Event + 只读视图(COW)

- 状态：✅（2026-10-15）
- 背景：Harness 要有唯一可信状态，支撑断点/回放/审计；同时策略层不能污染它。
- 决策：
  - **单写者**：只有 Kernel 经 `Command → reduce` 改状态；策略/UI/工具**只提交意图**，不直接改字段。
  - **两类通道**：`State`(权威·可序列化·可回放·可断点) 与 `Transient`(取消/在途 delta/进度心跳，**不进状态**，走事件流)。
  - **只读视图靠 COW**：策略拿按字段暴露的只读视图（看不到断点/权限/内部元数据）；用 copy-on-write/结构共享做到"不可变但不每轮全量深拷"。reduce **永远返回新 State、禁原地 mutate**；pydantic frozen 是浅冻结，**须配不可变集合**。
  - **Command=输入事件(可校验·可拒绝·非 append-only)；Event=输出事件(append-only·不可撤回·状态变更之后)**。**Event 不得反哺状态**，改状态只来自 Command。
  - 不变式（DAG 无环、tool_use/tool_result 配对等）在 **reduce 内部强制**，不靠调用方自觉。
- 后果：可信状态可回放可断点；代价=不可变数据结构有内存/CPU 权衡，需 COW 而非深拷。
- 备选(被否)：可变共享状态传引用（一改全崩、回放失效）→ 否；快照式全量深拷（长任务拷贝开销爆）→ 否。
- 关联：[`../design/01-state-model.md`](../design/01-state-model.md) §0/§7/§12、HARD-CONSTRAINTS C2/C5。
